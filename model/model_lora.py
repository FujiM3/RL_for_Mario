import torch  # 导入PyTorch主库（张量运算、保存/加载模型等）
from torch import optim, nn  # 从torch导入优化器模块和神经网络模块


# 定义LoRA网络结构（低秩适配器）
class LoRA(nn.Module):
    """LoRA 模块（低秩适配器）。

    由两个线性层 A（in->r）和 B（r->out）组成：先将输入投影到低秩空间，
    再恢复到输出维度。通常作为对原始线性层的加性修正使用。
    """
    def __init__(self, in_features, out_features, rank):
        super().__init__()  # 调用父类初始化，设置nn.Module内部结构
        self.rank = rank  # LoRA的秩（rank），控制低秩分解的中间维度大小
        self.A = nn.Linear(in_features, rank, bias=False)  # 低秩投影矩阵A（从输入到低秩空间）
        self.B = nn.Linear(rank, out_features, bias=False)  # 低秩投影矩阵B（从低秩空间回到输出）
        # 矩阵A高斯初始化，常用的小方差初始化以稳定训练
        self.A.weight.data.normal_(mean=0.0, std=0.02)
        # 矩阵B全零初始化，常见做法是让B初始为0以便开始时不干扰原模型

        # 若均为高斯初始化，训练可能影响模型性能导致不稳定或难以收敛
        # 若均为0初始化，则没有学习信号（全部为0）也不可取
        self.B.weight.data.zero_()  # 将B的权重置为0，保证初始阶段LoRA不改变原有模型输出

    def forward(self, x):
        # 先通过A映射到低秩空间，再通过B映射回输出空间，完成低秩近似的线性变换
        return self.B(self.A(x))


def apply_lora(model, rank=8):
    """为模型中选定的 nn.Linear 层挂载 LoRA 适配器。

    本函数遍历模型子模块（按启发式选择目标），为每个目标线性层创建 LoRA
    子模块并将其 forward 替换为原始输出与 LoRA 输出相加的版本，从而启用低秩微调。
    """
    # 遍历模型所有子模块，寻找可以替换或增强的线性层
    for name, module in model.named_modules():  # 获取model中所有的子模块（name为模块名，module为模块对象）
        # 若为线性层且权重矩阵为方阵（常用于自注意力的投影矩阵），则为该层添加LoRA模块
        if isinstance(module, nn.Linear) and module.weight.shape[0] == module.weight.shape[1]:
            # 创建LoRA模块，in/out维度取自线性层的权重形状，并移动到模型所在设备
            lora = LoRA(module.weight.shape[0], module.weight.shape[1], rank=rank).to(model.device)
            # (module.weight.shape[0] * rank) * (rank * module.weight.shape[1])
            #              A                                  B  
            setattr(module, "lora", lora)  # 将LoRA对象挂载到原模块上，属性名为'lora'
            original_forward = module.forward  # 保存原始的forward函数

            # 显式绑定：定义一个新的forward函数，使原始输出与LoRA输出相加
            def forward_with_lora(x, layer1=original_forward, layer2=lora):
                return layer1(x) + layer2(x)  # 原始线性变换输出 + LoRA的低秩修正

            module.forward = forward_with_lora  # 将模块的forward替换为新的forward


def load_lora(model, path):
    """从磁盘加载 LoRA 参数并注入到模型中对应的 lora 子模块。

    支持处理可能存在的 'module.' 前缀（如 DataParallel 保存的权重），
    并仅为模型中挂载了 'lora' 属性的子模块加载参数。
    """
    # 存在可以复用的可能性，当新任务和原任务相近时，加载LoRA权重可以加速训练收敛（作为预热）并提升性能，尤其在数据有限的情况下。
    # 从文件加载LoRA的状态字典，加载到模型所在设备
    state_dict = torch.load(path, map_location=model.device)
    # 如果保存时带有'module.'前缀（比如DataParallel），则去掉该前缀以匹配当前模型的命名
    state_dict = {(k[7:] if k.startswith('module.') else k): v for k, v in state_dict.items()}

    # 遍历模型，找到挂载了'lora'属性的模块并加载对应的LoRA参数
    for name, module in model.named_modules():
        if hasattr(module, 'lora'):
            # 从整体state_dict中筛选出属于当前模块的LoRA参数，并去掉模块名前缀
            lora_state = {k.replace(f'{name}.lora.', ''): v for k, v in state_dict.items() if f'{name}.lora.' in k}
            module.lora.load_state_dict(lora_state)  # 将参数加载到模块的lora子模块中


def save_lora(model, path):
    """保存模型中所有 LoRA 子模块的参数到指定路径。

    只导出挂载在模块上的 lora 子模块参数（以模块名为前缀），便于单独分发或加载 LoRA 权重。
    """
    # 获取原始模型（有时包装在_parallel或其他容器下，_orig_mod用于取回原始模型）
    raw_model = getattr(model, '_orig_mod', model)
    state_dict = {}  # 准备一个字典存放所有LoRA模块的参数，按模块名组织
    for name, module in raw_model.named_modules():
        if hasattr(module, 'lora'):
            # 清理模块名中可能的'module.'前缀，保证存储的键名稳定
            clean_name = name[7:] if name.startswith("module.") else name
            # 将当前LoRA模块的参数加入到全局state_dict，键名格式为'{模块名}.lora.{参数名}'
            lora_state = {f'{clean_name}.lora.{k}': v for k, v in module.lora.state_dict().items()}
            state_dict.update(lora_state)  # 合并到总字典中
    torch.save(state_dict, path)  # 将所有LoRA参数保存到指定路径
