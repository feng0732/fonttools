# fontTools varLib 稀疏增量（IUP）恢复机制分析

> 分析对象：`Lib/fontTools/varLib/iup.py`（fontTools 4.68.1.dev0，工作树版本，纯 Python 模式
> `cython.compiled == False`；Cython 编译路径与纯 Python 路径源码相同）。
> 本文只做静态阅读与只读实验，不修改任何源码。所有可执行结论均由隔离目录
> `/tmp/iup-experiments/` 下的脚本用 `python3 -I` 复现，`Tests/varLib/iup_test.py`
> 的 29 个用例在分析时全部通过。

## 1. 背景与术语

OpenType `gvar` 表允许一个字形变体只在部分轮廓点上存储**显式增量**（explicit delta），
其余点的增量写成“推断点”（inferred point，fontTools 内部用 Python 的 `None` 表示）。
渲染器在应用变体前必须把缺失增量恢复出来，这套规则在 OpenType 规范中称为
**IUP（Interpolation of Unreferenced Points，未引用点插值）**。fontTools 中它有两个方向：

| 方向 | 入口函数 | 作用 |
|---|---|---|
| 恢复（解码侧） | `iup_segment` → `iup_contour` → `iup_delta`（`iup.py:44,95,147`） | 把含 `None` 的稀疏增量向量补全为稠密向量 |
| 优化（编码侧） | `can_iup_in_between`、`_iup_contour_bound_forced_set`、`_iup_contour_optimize_dp`、`iup_contour_optimize`、`iup_delta_optimize`（`iup.py:196,242,332,397,541`） | 在误差容限内把尽可能多的显式增量替换成 `None` |

调用方：

- 构建：`varLib/__init__.py:426` 的 `_add_gvar` 对每个变体调
  `TupleVariation.optimize(..., tolerance=0.5)`（`TupleVariation.py:619-646`）；
- 实例化/取参：`mutator.py:246`、`ttLib/ttGlyphSet.py:349`、
  `TupleVariation.calcInferredDeltas`（`TupleVariation.py:606-617`）、
  `instancer/__init__.py:625` 在遇到含 `None` 的变体时调 `iup_delta` 恢复；
- 编译：`TupleVariation.compilePoints`（`TupleVariation.py:211` 起）把“哪些点有显式增量”
  编码成 gvar 的点编号 run，`None` 不占增量数据，只占点集编码的开销。

几何输入 `coords` 总是包含 **4 个幻影点**（phantom points），由
`glyf._getPhantomPoints` / `_getCoordinatesAndControls`
（`ttLib/tables/_g_l_y_f.py:388-474`）追加在真实轮廓点之后，顺序为
左、右、上、下：`(leftSideX,0)`、`(rightSideX,0)`、`(0,topSideY)`、`(0,bottomSideY)`。
`iup_delta` 的断言 `len(coords) == (ends[-1]+1 if ends else 0) + 4`（`iup.py:156`）
把这一约定写死了；函数内部再把 4 个幻影点当作 4 个独立的单点“轮廓”追加到 `ends`
（`iup.py:158,556`）。

## 2. 恢复算法（`iup_segment` / `iup_contour` / `iup_delta`）

### 2.1 单段插值 `iup_segment`（`iup.py:44-92`）

给定两个**参考（锚点）坐标** `rc1, rc2` 及其增量 `rd1, rd2`，对 `coords` 中每个点、
**x 与 y 两个轴分别独立**计算恢复增量。对任一轴：

1. 若 `rc1[j] == rc2[j]`（两锚点在该轴坐标相同）：
   - 两锚点增量也相同 → 该段所有点取该常量增量；
   - 两锚点增量不同 → 该段所有点恢复为 **0**（`iup.py:58-64`）。
2. 否则按坐标排序锚点，使 `x1 < x2`，斜率 `scale = (d2-d1)/(x2-x1)`。对目标点坐标 `x`：
   - `x <= x1`：**钳制**为 `d1`；
   - `x >= x2`：**钳制**为 `d2`；
   - `x1 < x < x2`：线性插值 `d = d1 + (x-x1)*scale`（`iup.py:75-88`）。

注意三点：（a）这是按**默认主坐标系下的几何坐标**做的插值，不是按点序号；
（b）区间外不做外推，而是取最近锚点的增量（钳制/平台）；
（c）`iup.py:82-88` 刻意保留中间变量 `nudge` 以关闭融合乘加优化，注释指向
[issue #3703](https://github.com/fonttools/fonttools/issues/3703)，保证浮点结果逐位稳定。

### 2.2 闭合轮廓的首尾锚点选择（`iup_contour`，`iup.py:95-144`）

轮廓被视为**循环序列**，锚点就是 `deltas` 中所有非 `None` 的下标 `indices`。
缺失点取其**循环序两侧最近的两个显式点**为锚点，与轮廓的物理起点（下标 0）无关：

- 若第一个显式点 `start != 0`，下标 `[0, start)` 的前缀缺失段要“跨过接缝”回绕：
  锚点为 `start` 与**最后一个**显式点 `indices[-1]`（`iup.py:115-122`）；
- 中间每对相邻显式点之间若有缺口，用这两个显式点自身做锚点（`iup.py:124-133`）；
- 若最后一个显式点不在 `n-1`，后缀缺失段 `[start+1, n)` 同样回绕，锚点为
  `start` 与**第一个**显式点 `indices[0]`（`iup.py:134-141`）。

实测（实验 2）：5 点闭合轮廓，仅点 1（锚点增量 `(0,0)`）和点 4（`(4,0)`）显式，
点 0 的 x 坐标 10 落在两锚点 x 坐标 0 与 20 之间，恢复出 `(2,0)`——即首尾接缝处
由点 4 与点 1 跨接插值，点 2、3 则在点 1→点 4 的正向区间内恢复。

### 2.3 哪些点会被强制保留 / 得到零增量

**恢复侧**只有两种退化情形（`iup.py:102-110`）：

- 轮廓内完全没有 `None`：原样返回；
- 轮廓内**一个显式增量都没有**（`indices` 为空）：整段返回 `[(0,0)] * n`。
  这就是“没有有效锚点时”的确定结果——零向量，而不是向其他轮廓借锚点。

**优化侧**的“强制保留集合”由 `_iup_contour_bound_forced_set`（`iup.py:242-320`）
逐点、逐轴计算。docstring 声称该集合是**精确的**（precise）：在集合内的点，给定
坐标与全量增量后，不存在任何 IUP 编码能产生它。判定规则（对每个轴，取循环左右邻居
`lc, nc` 与增量 `ld, nd`）：

1. 邻居坐标相等（`c1 == c2`）：若邻居增量之差超出容限**且**当前点增量本身超出容限，
   强制（`iup.py:284-286`）。该测试必须先于下一条（注释明示）。
2. 当前点坐标夹在两邻居坐标之间，但其增量**不**夹在两邻居增量之间（含容限），
   强制（`iup.py:293-295`）。
3. 当前点坐标在邻居区间之外：增量必须与最近邻居一致、或与插值同号，否则强制
   （`iup.py:299-314`）。

任一轴命中即加入 `forced` 并跳出该点的另一轴检查（`iup.py:316-318`）。
`Tests/varLib/iup_test.py:13-115` 的 `test_forced_set` 固定了这些结果，例如
旋转增量的正方形四角得到空集，而 12 点字形得到 `{11}`、25 点字形得到 `{5,15,24}`；
同一测试还断言“带 forced 与不带 forced 的 DP 产出相同的 chain/costs”，即强制集合
只剪枝、不改最优值。

### 2.4 优化器如何处理缺失增量

`iup_contour_optimize`（`iup.py:397-538`）先处理三个捷径，再走动态规划：

1. 所有增量都在容限内等价于 0 → 全部返回 `None`（`iup.py:416-427`）。
   当 `tolerance >= 0.5` 时还要额外检查 `otRound` 后的增量仍在容限内（取整闸门）；
2. 单点轮廓 → 原样返回；
3. 所有增量**完全相等** → 只保留第一个，其余 `None`（`iup.py:434-436`）。
   恢复时单点锚点即可把常量传播到整段。

一般情形用 DP（`_iup_contour_optimize_dp`，`iup.py:332-377`）：`costs[i]` 是
“点 i 必须显式编码时，0..i 的最少显式点数”，从候选前驱 `j` 中用
`can_iup_in_between` 检查 `(j,i)` 之间能否由两端插值恢复；遇到 forced 点立即停止
向后回溯（`iup.py:362-375`）。DP 本身带“最后一点必须显式”的约束，外层用两种方式
解除循环问题：

- **forced 非空**：把轮廓旋转，使最大 forced 点落到末尾，DP 后再旋转回去
  （`iup.py:458-498`）。这条路径的最优性由 forced 集合的精确性保证；
- **forced 为空**：把轮廓重复拼接成长度 `2n` 的线性问题，在长度为 n 的窗口里找
  闭环解（`iup.py:499-536`）。源码注释直说
  “I cannot prove that this always produces the optimal solution...”
  （`iup.py:500-502`）——**最优性在此分支没有证明，属于已知的推断/证据缺口**。

回溯窗口还有硬上限 `MAX_LOOKBACK = 8`（`iup.py:29,351-353`）：即使全线性可插值，
单点跨越的候选前驱也不超过 8 个位置。实测 20 个共线、增量严格线性的点，保留的
显式下标为 `[0, 7, 14, 19]`（4 个锚点），重建仍然逐点精确。

`can_iup_in_between`（`iup.py:196-229`）的容限度量是二维欧氏模
`abs(complex(dx, dy)) <= tolerance`，即误差圆而非逐轴矩形。

### 2.5 坐标取整

OpenType 轮廓坐标与 gvar 增量落盘前都要取整，`otRound`（`misc/roundTools.py:38-59`）
实现为 `floor(v + 0.5)`（半值向 `+∞`）。优化器因此做**双重重建校验**：

- `_iup_round_points`（`iup.py:173-181`）对含非整数的坐标/增量各算一份取整副本；
  若两份输入本来就全是整数，则跳过（`rounded_* is None`，`iup.py:440-441`）；
- `can_iup_in_between` 先在实数数据上校验，再在取整数据上校验一次，两次都过才算
  可插值（`iup.py:210-229`）；
- forced 集合同样在实数与取整两份数据上各算一次并取并集（`iup.py:445-449`）；
- 被保留的显式增量**保留原始浮点值**，docstring 明确
  “Retained deltas preserve their original values”（`iup.py:406-408`），
  测试 `test_optimize_fractional_contours` 逐条断言
  `d is None or d == original`（`iup_test.py:228-230`）。

instancer 侧在重新优化前先把坐标 `coordinates.toInt()` 取整，注释
（`instancer/__init__.py:1057-1066`）说明原因：IUP 语义依赖点相等性，必须让优化时
的比较与渲染时一致；对应回归测试 `test_rounds_before_iup`
（`Tests/varLib/instancer/instancer_test.py:4790`，issue #3634）。

### 2.6 跨轮廓起点与幻影点的独立性

`iup_delta` / `iup_delta_optimize` 按 `ends` 把坐标切成若干轮廓，**逐轮廓独立**调
`iup_contour(_optimize)`，结果拼接（`iup.py:159-167,558-565`）。轮廓之间不共享锚点、
不回绕跨界。4 个幻影点各自成为长度为 1 的独立“轮廓”：

- 单点轮廓若增量为 `None` → 恢复为 `(0,0)`；若有显式增量 → 原样保留；
- 因此**真实轮廓的锚点永远不能用来推断幻影点，反之亦然**。实测（实验 7）：
  零轮廓字形（如空格）只有 4 个幻影点，仅右幻影（步进宽）带 `(50,0)`，
  `iup_delta` 输出 `[(0,0),(50,0),(0,0),(0,0)]`；
- 优化侧同理：两个水平幻影带相同的 `(50,0)` 时，因分属不同单点轮廓，无法合并，
  实测 `iup_delta_optimize` 保留两个显式增量（实验 11）；全部为零时才各自走
  “全 None”捷径。

复合字形没有真实轮廓点，`ends` 是组件下标列表（`_g_l_y_f.py:448-460`），
同样附加 4 个幻影点后走同一套流程。

## 3. 一个“保持插值却减少显式增量”的例子

4 点直线轮廓，y 恒为 0，x 坐标等距、x 增量随 x 线性：

```
coords = [(0,0), (10,0), (20,0), (30,0)]
deltas = [(0,0), (1,0), (2,0), (3,0)]
```

`iup_contour_optimize(..., tolerance=0)` 输出：

```
[(0,0), None, None, (3,0)]      # 4 个显式增量 -> 2 个
```

只保留首尾两个锚点。恢复时 `iup_contour` 用锚点 `(x=0,d=0)` 与 `(x=30,d=3)`
对中间点做线性插值，得到 `[(0,0),(1.0,0),(2.0,0),(3.0,0)]`，与原始增量**逐点相等**
（实验 1，已运行验证）。几何上，实例位置 = 默认坐标 + 恢复增量，因此轮廓结果与
全量编码完全一致；省掉的是 gvar 里两个点的 delta 数据与对应点集 run 开销。
`iup_test.py` 中 `test_optimize_equal_rounded_deltas`、
`test_optimize_preserves_rounded_interpolation` 等用例覆盖了同类性质
（含旋转起点与容限参数化）。

## 4. 两个会改变恢复结果的反例

以下两例都对比“朴素线性外推/均值直觉”与 IUP 实际输出，数值均由实验 4、5 实测。

### 反例 A：锚点同轴坐标相等但增量不同 → 恢复为 0，而非中间值

```
coords = [(0,0), (0,10), (0,20)]          # 三个点 x 坐标都是 0
deltas = [(1,0), None, (3,0)]             # 两锚点 x 增量 1 与 3
iup_contour -> [(1,0), (0,0), (3,0)]
```

直觉上中点或许该得到 `(2,0)`；但 `iup_segment` 的 `x1 == x2` 分支
（`iup.py:58-64`）在 `d1 != d2` 时直接产出 0，因为在一条退化（零长度基向量）的
插值轴上无法定义有意义的斜率。对照实验：把坐标改成 `(0,0),(10,10),(20,20)`，
同样的增量就恢复出中点 `(2,0)`。优化侧对应 `_iup_contour_bound_forced_set`
的第一条规则（`iup.py:284-286`），这类点会被强制保留为显式点，无法靠 IUP 表达。
`iup_test.py:138-143` 的 `test_interpolate_fractional_reference_deltas` 固定了该行为
（分数锚点 `1.5` 与 `2`、共享 x=0 时中点恢复为 0）。

### 反例 B：目标点落在锚点坐标区间之外 → 钳制，而非外推

```
coords = [(0,0), (10,0), (20,0), (30,0), (40,0)]
deltas = [None, (0,0), None, None, (4,0)]   # 锚点在 x=10 与 x=40
iup_contour -> [(0,0), (0,0), (1.333,0), (2.667,0), (4,0)]
```

若按线性公式外推，点 0（x=0）应得 `-4/3`；实际被**钳制**为最近锚点增量 `0`
（`iup.py:75-78`）。区间内的点 2、3 正常插值，所有恢复值都被夹在 `[d1, d2]` 内。
这意味着把一个显式点删掉、让它落到锚点 bracket 之外时，恢复结果是平台值而不是
延长线——优化器的 forced 集合第三条规则（`iup.py:299-314`）正是用来识别
“外推方向上增量符号不一致、必须显式保留”的点。

### 补充反例（取整）：实数可插值，取整后不可插值

搜索脚本 `search_rounding.py` 在 1/8 网格上找到的最小实例（实验 8b，已实测）：

```
coords = [(-0.875,0), (-0.75,0), (-0.5,0), (-0.375,0)]
         otRound -> [(-1,0), (-1,0), (0,0), (0,0)]
deltas = [(0,0), (0.125,0), (0.375,0), (0.5,0)]
         otRound -> [(0,0), (0,0), (0,0), (1,0)]
```

实数数据下 `can_iup_in_between(0, 3)` 为真（增量随坐标严格线性）；取整后锚点 0、3
的坐标分别与邻居重合且增量不同，校验为假。若优化器只看实数、只留首尾两个锚点，
gvar 解码（取整坐标 + 取整增量）会在点 2 错误恢复出 `(1,0)`，而真实取整增量是
`(0,0)`。当前双重校验把点 2 保留为显式锚点，实际输出
`[(0,0), None, (0.375,0), (0.5,0)]`，取整重建与正确值一致。这直接解释了
`iup.py:216-229` 的第二段校验与 `iup_test.py:123-136,172-193` 两组取整测试存在的
必要性。

## 5. 当前实现 / 推断 / 证据缺口

### 5.1 由源码与测试直接确认（当前实现）

- 分轴独立插值；同坐标异增量 → 0；区间外钳制不外推；浮点 FMA 禁用（`iup.py:44-92`）。
- 闭合轮廓按循环序选最近显式点为锚点，首尾两段可跨接缝回绕（`iup.py:115-141`）。
- 无锚点轮廓整体恢复 `(0,0)`；全零/单点/全等增量三条捷径（`iup.py:108-110,416-436`）。
- forced 集合的三条判定规则及其“精确性”声明；DP 遇 forced 即剪枝
  （`iup.py:242-320,362-375`），`iup_test.py:113-121` 验证剪枝不改最优值。
- `MAX_LOOKBACK = 8` 的窗口上限；取整双校验与 forced 并集；保留增量不改原值
  （`iup.py:29,351-353,438-449`）。
- 轮廓与 4 个幻影点逐段独立，幻影点互为隔离的单点轮廓（`iup.py:156-167`；
  `_g_l_y_f.py:415-420,470-472`）。
- 构建侧默认 `tolerance=0.5`（`varLib/__init__.py:362,426`），且只有优化后
  实际编译体积更小时才采纳（`TupleVariation.py:634-646`）。

### 5.2 合理推断（代码行为支持，但无显式规范文本/测试逐条锁定）

- 容限用二维模 `abs(complex(...))` 意味着 x、y 误差可互相补偿（误差圆）；
  源码没有注释解释为何不用逐轴判定，测试只验证圆内样例，未锁定圆外角落行为。
- 无 forced 分支的“重复轮廓 + 滑动窗口”DP 在注释中自认无法证明最优
  （`iup.py:500-502`）；现有测试（含 200 组随机轮廓的
  `test_optimize_fractional_contours`，`iup_test.py:212-244`）只验证**可行性**
  （重建误差达标、原值不被改写），没有断言该分支产出全局最少锚点数。
- 旋转实验（本文实验 13）显示同一闭合轮廓在不同起点下显式点数相同但点位集合不同，
  与 lookback 截断和 DP 平局时的遍历顺序有关；源码未承诺旋转不变性，测试也未覆盖。
- `TupleVariation.optimize` 以“编译后字节数更小”为最终采纳条件，因此 IUP 产出
  最少 `None` 数不等于最终一定写入字体——这是体积层面的推断，没有测试直接构造
  “IUP 更优但被字节数比较否决”的 gvar 用例。

### 5.3 证据缺口（本次分析无法从仓库内闭环的部分）

- 本仓库是浅克隆（仅 1 个提交），`iup.py` 的演进历史、issue #3282（被注释掉的
  tolerance 类型声明，`iup.py:189`）、#3703、#3634 的讨论原文无法在本地核对，
  只能依据代码注释与回归测试名转述。
- Cython 编译产物未参与实验（环境中 `COMPILED == False`）。`cython.cfunc`/`locals`
  声明在编译后可能引入与纯 Python 不同的数值提升路径，本文的浮点级结论
  （如 `nudge` 的逐位稳定性）未在编译模式下实测。
- IUP 与 OpenType 规范文本（Apple/OT 对 inferred delta 的官方定义）的一致性未做
  外部比对；仓库内 `Doc/source/varLib/iup.rst` 只有 `automodule` 指令，无人工文档。
- CFF2 路径（`varLib/cff.py`）使用 ItemVariationStore 而非 gvar 点集，不经过
  `iup.py`；本文结论严格限定于 glyf/gvar（及 `gvar` 风格的 2D TupleVariation；
  1D 的 cvar 在 `calcInferredDeltas` 入口即被拒绝，`TupleVariation.py:609-610`）。

## 6. 关键文件与测试索引

| 主题 | 位置 |
|---|---|
| 段/轮廓/全字形恢复 | `Lib/fontTools/varLib/iup.py:44,95,147` |
| 容限判定、forced 集合、DP | `iup.py:196,242,332` |
| 轮廓级优化与两条循环分支 | `iup.py:397-538` |
| 全字形优化入口 | `iup.py:541-567` |
| 取整策略 `otRound` | `Lib/fontTools/misc/roundTools.py:38-59` |
| 幻影点定义与追加 | `Lib/fontTools/ttLib/tables/_g_l_y_f.py:388-474` |
| 变体优化/恢复封装 | `Lib/fontTools/ttLib/tables/TupleVariation.py:606-646` |
| 构建侧调用（tolerance=0.5） | `Lib/fontTools/varLib/__init__.py:362-427` |
| 实例化前取整（#3634） | `Lib/fontTools/varLib/instancer/__init__.py:1057-1068` |
| IUP 单元测试（29 项，全过） | `Tests/varLib/iup_test.py` |
| 取整回归测试 | `Tests/varLib/instancer/instancer_test.py:4790-4825` |
| 变体级 optimize/inferred 测试 | `Tests/ttLib/tables/TupleVariation_test.py:1001-1006,1059-1064` |
| mutator 端到端 IUP 字体 | `Tests/varLib/mutator_test.py:167-187` |
