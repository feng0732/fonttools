# TrueType 全离曲线轮廓的隐含起点：fonttools 实现追踪报告

- 仓库：`fonttools`（分支 `task/114`，HEAD `f3f799e`）
- 方法：纯源码静态分析 + 只读行为验证（未修改仓库任何文件）
- 涉及文件：
  - `Lib/fontTools/pens/ttGlyphPen.py`
  - `Lib/fontTools/pens/pointPen.py`
  - `Lib/fontTools/pens/basePen.py`
  - `Lib/fontTools/pens/filterPen.py`
  - `Lib/fontTools/ttLib/tables/_g_l_y_f.py`
  - `Tests/pens/ttGlyphPen_test.py`、`Tests/pens/pointPen_test.py`、`Tests/ttLib/tables/_g_l_y_f_test.py`、`Tests/pens/filterPen_test.py`

---

## 1. 隐含起点如何被推导、moveTo / closePath 何时发出

### 1.1 规范背景

TrueType `glyf` 轮廓只存点序列和 on-curve 标志位。两个相邻离曲线（off-curve）点之间隐含一个位于其连线中点的 on-curve 点。当一条轮廓**没有任何 on-curve 点**时，第一个隐含 on-curve 点取"最后一个存储点与第一个存储点的中点"，它同时充当轮廓的隐含起点（implicit start point）。因此**存储顺序（哪个离曲线点排在首位）直接决定隐含起点落在哪一对点上**，但不改变渲染几何——所有相邻点对的中点集合是旋转不变的。

### 1.2 绘制层：`Glyph.draw()`（`_g_l_y_f.py:1585-1687`）

这是从 glyf 数据推导隐含起点的核心代码，分三种情形：

1. **全离曲线 + 三次（flagCubic）**（`_g_l_y_f.py:1617-1632`）：
   ```python
   l = contour[-1]; f = contour[0]
   p0 = (maybeInt((l[0]+f[0])*0.5), maybeInt((l[1]+f[1])*0.5))
   pen.moveTo(p0)
   ```
   首末点中点显式算出后立即 `moveTo(p0)`，随后每两个离曲线点发出一个 `curveTo`，段与段之间的 on-curve 点同样是相邻控制点的中点。点数必须为奇数段配对（`assert count % 2 == 0`，`:1619`）。

2. **全离曲线 + 二次**（`_g_l_y_f.py:1633-1638`）：不显式算中点，而是
   ```python
   contour.append(None)
   pen.qCurveTo(*contour)
   ```
   把 `None` 作为末参数，把"推导隐含起点"的职责下放给 pen 协议（见 1.3）。

3. **含 on-curve 点**（`_g_l_y_f.py:1640-1647`）：先旋转点列使轮廓**以第一个 on-curve 点结尾**，再 `pen.moveTo(contour[-1])`。即 moveTo 的目标是存储序列中的第一个 on-curve 点，而非第一个存储点。

   主循环里，若下一个 on-curve 就是轮廓末尾（`nextOnCurve == 1` 且 `len(contour) == 1`），**跳过最后的 `lineTo`**，因为它被随后的 `pen.closePath()` 隐含（`:1650-1654`）。每条轮廓无条件以 `pen.closePath()` 结束（`:1687`）——TrueType 轮廓永远闭合。

`Glyph.drawPoints()`（`:1689-1742`）则**不做任何旋转**，按存储顺序原样发点以保持点索引不变；代价是全离曲线的**三次**轮廓无法表达，直接抛 `NotImplementedError`（`:1713-1716`，测试 `Tests/ttLib/tables/_g_l_y_f_test.py:1087` `test_drawPoints_all_offcurve`）。全离曲线的二次轮廓在点笔协议里用"全部 `segmentType=None`"自然表达，无需特殊处理。

### 1.3 段笔层：`BasePen.qCurveTo()` 的 `None` 特例（`basePen.py:369-395`）

当 `qCurveTo` 的最后一个参数为 `None`（即全离曲线二次轮廓）：

```python
x, y = points[-2]   # 最后一个离曲线点
nx, ny = points[0]  # 第一个离曲线点
impliedStartPoint = (0.5 * (x + nx), 0.5 * (y + ny))
self.__currentPoint = impliedStartPoint
self._moveTo(impliedStartPoint)          # ← moveTo 在此发出
points = points[:-1] + (impliedStartPoint,)
```

隐含起点 = **首末离曲线点的中点**，`moveTo` 在替换末点之前发出。之后 `decomposeQuadraticSegment()`（`basePen.py:433-452`）在每对相邻离曲线点之间插入中点（`impliedPt`，`:449`）逐段拆分。`curveTo` 的超贝塞尔分解（`decomposeSuperBezierSegment`，`:398-430`）用同一"中点即隐含 on-curve"原则处理多控制点三次曲线。

### 1.4 点笔协议层（`pointPen.py`）

- **`BasePointToSegmentPen.endPath()`**（`pointPen.py:157-203`）：闭合轮廓先找第一个 on-curve 点并把点列旋转到以它结尾（`:181-193`）；若**找不到任何 on-curve 点**，则追加哨兵点 `(None, "qcurve", None, None, None)`（`:187-191`），把整个轮廓打包成一个以 `None` 结尾的 qcurve 段。
- **`PointToSegmentPen._flushContour()`**（`pointPen.py:227-290`）：闭合路径的 moveTo 目标取"最后一段的最后一个点"（`:243-244`）；若该点为 `None`（全离曲线特例），**跳过 moveTo**（`:245-249`），直接发 `qCurveTo(*含None)`，由下游（如 1.3 的 BasePen）决定隐含起点。此外，闭合轮廓末尾的 `lineTo` 默认省略（被 closePath 隐含），但当末点与起点重合时必须显式输出以区分"重复点"与"隐含闭合力线"（`:262-277`，注释引用 fontmake#572；测试 `test_closed_line_overlapping_start_end_points`，`Tests/pens/pointPen_test.py:179`）。
- **`SegmentToPointPen.closePath()`**（`pointPen.py:349-372`）：仅当首末点**都是 on-curve**（`segmentType is not None`）时才删除末尾重复点；全离曲线 blob 的每个点都必须保留（`:353-364`，注释引用 issue #4014）。否则把首点的 `"move"` 改为 `"line"`（闭合轮廓没有 move）。
- **`ReverseContourPointPen`**（`pointPen.py:476-539`）：见 §3.1。

### 1.5 落盘层：`TTGlyphPen` / `TTGlyphPointPen`（`ttGlyphPen.py`）

**`TTGlyphPen`（段笔）**：

- `moveTo`（`:207-210`）：仅当上一轮廓已闭合才允许，点以 `flagOnCurve` 记录。
- `qCurveTo`（`:221-228`）：除末点外全部以 flag `0`（二次离曲线）记录；**末点为 `None` 时不记录任何点**——全离曲线轮廓就这样原样落盘，隐含起点不在 glyf 数据里显式存在。
- `closePath()`（`:230-247`）三个关键决策：
  1. **单点轮廓被丢弃**：`endPt == 0` 或轮廓只有一点时 `_popPoint()` 直接返回（`:233-236`，"ignore anchors"，测试 `test_closePath_ignoresAnchors`，`Tests/pens/ttGlyphPen_test.py:55`）；
  2. `outputImpliedClosingLine=False`（默认）时，若末点坐标等于首点则**弹出末点**（`:238-245`）——注意这里**不检查点的 on-curve 类型**，见 §3.2；
  3. 把 `endPt` 追加进 `endPtsOfContours`，轮廓闭合。
- `endPath()` 直接调用 `closePath()`（`:249-251`），因为 TrueType 轮廓永远闭合。
- `glyph()`（`:129-167`）：轮廓未闭合抛 `PenError`（`:144-145`）；`dropImpliedOnCurves=True` 时调用 `dropImpliedOnCurvePoints(glyph)`（`:163-164`）。

**`TTGlyphPointPen`（点笔）**：`beginPath`/`endPath`/`addPoint`（`:273-336`）原样存储点；`endPath` 跳过空轮廓（`:288-291`），并把 `"curve"` 类型点**向前回溯**把前面的离曲线点标记为 `flagCubic`，索引在轮廓边界处回绕（`:297-309`）。点笔不做任何去重——重复点全部保留（测试 `test_keep_duplicate_end_point`，`Tests/pens/ttGlyphPen_test.py:392`）。

### 1.6 反向操作：`dropImpliedOnCurvePoints()`（`_g_l_y_f.py:1767-1860`）

把"位于两个相邻离曲线点中点"的 on-curve 点从 glyph 里删除（可跨插值 master 取交集，`:1833-1837`）。判定函数 `_is_mid_point`（`:1759-1764`）有两个分支：精确中点（`isclose`）**或** otRound 取整后的中点相等。删除全部可隐含的 on-curve 点后，轮廓就变成全离曲线轮廓，其隐含起点由 §1.2 的规则在绘制时重新推导。测试：`test_dropImpliedOnCurvePoints_all_quad_off_curves` / `_all_cubic_off_curves` / `_not_all_impliable`（`Tests/ttLib/tables/_g_l_y_f_test.py:1381,1436,1473`）。

---

## 2. 边界形态比较与几何等价例

### 2.1 四种边界形态对比

| 形态 | 各层行为 | 关键源码 |
|---|---|---|
| **单点轮廓** | `TTGlyphPen.closePath` 直接丢弃（"anchor"）；`BasePointToSegmentPen.endPath` 对单点路径发 `("move", ...)` 开放段（`pointPen.py:164-169`）；`TTGlyphPointPen.endPath` 只跳过**空**轮廓，单点轮廓保留 | `ttGlyphPen.py:233-236`；`pointPen.py:164-169`；`ttGlyphPen.py:288-291` |
| **重复点** | 点笔路径（`SegmentToPointPen`）只在首末皆 on-curve 时去重；段笔路径（`TTGlyphPen.closePath`）默认不区分类型去重（§3.2）；`outputImpliedClosingLine=True` 时保留闭合力线重复点 | `pointPen.py:353-364`；`ttGlyphPen.py:238-245`；测试 `ttGlyphPen_test.py:299` |
| **混合曲线** | 同一轮廓内 cubic 与 quadratic 离曲线点混排在 `Glyph.draw` 里是未定义的：`assert all(cubicFlags) or not any(cubicFlags)`，混合时抛 "Mixed cubic and quadratic segment undefined"；奇数个三次离曲线点同样未定义 | `_g_l_y_f.py:1657-1670,1619` |
| **嵌套复合字形** | `_buildComponents`：若 glyph 同时有轮廓和组件，组件被 `_decompose` 展开为轮廓（`ttGlyphPen.py:102-105`）；纯组件时嵌套复合经 `TransformPen` 展平为单层组件列表，组件偏移在每层 `otRound`，而轮廓坐标只在 `glyph()` 末尾统一取整（`:165`），避免中间舍入累积 | `ttGlyphPen.py:56-62,88-127`；测试 `test_composite_bounds_with_nested_components`（`ttGlyphPen_test.py:617`）、`test_glyph_decomposes`（`:86`） |

复合字形本身不存轮廓点，因此"隐含起点"问题只在组件被分解（decompose）时出现——分解后走的正是 §1.2 的 `Glyph.draw` 路径。

### 2.2 等价例 1：旋转全离曲线轮廓 —— 起点不同，几何相同

同一二次 blob 的两种存储顺序：

```python
# 顺序 A：[(10,20), (20,20), (20,10), (10,10)]，全部 off-curve
# 顺序 B：[(20,20), (20,10), (10,10), (10,20)]（A 旋转一位）
```

- 隐含起点：A 为 `(10,20)` 与 `(10,10)` 的中点 **(10, 15)**；B 为 `(20,20)` 与 `(20,10)` 的中点 **(15, 20)**（`basePen.py:379-384`；行为已用本仓库 `Lib/` 实测确认）。
- 几何：相邻点对集合相同 → 隐含中点集合相同 → 四条二次贝塞尔段完全相同，仅遍历起点不同。

对应测试：`test_quad2` / `test_roundTrip2`（`Tests/pens/pointPen_test.py:274,307`）锁定 `None` 结尾 qCurveTo 的往返；`test_drawPoints_all_offcurve`（`_g_l_y_f_test.py:1087`）锁定全离曲线二次轮廓 `drawPoints` 不改变点序。

### 2.3 等价例 2：显式 on-curve 起点 vs `dropImpliedOnCurvePoints` 后的全离曲线轮廓

以 `test_dropImpliedOnCurvePoints_all_quad_off_curves`（`_g_l_y_f_test.py:1381`）为例：

```python
# 删除前（8 点）：(0,1) on-curve, (1,1) off, (1,0) on-curve, (1,-1) off, ...
# 删除后（4 点）：(1,1), (1,-1), (-1,-1), (-1,1)，全部 off-curve
```

- 起点：删除前 moveTo 目标是显式 on-curve 点 `(0,1)`；删除后隐含起点变成首末离曲线点 `(1,1)`、`(-1,1)` 的中点——恰好又是 `(0,1)`。
- 几何：被删的点严格位于相邻离曲线点中点（`_is_mid_point`，`_g_l_y_f.py:1759-1764`），绘制时按 §1.2/§1.3 规则重新隐含出来，渲染结果逐点相同，但存储的起点索引和点数都不同。

另一个同族等价：`SegmentToPointPen.closePath` 把闭合轮廓首点的 `"move"` 改写为 `"line"`（`pointPen.py:365-370`），以及 `TTGlyphPen.closePath` 删除与首点重合的末点（测试 `test_remove_extra_move_points`，`ttGlyphPen_test.py:117`）——存储的起点标记/点数不同，轮廓几何不变。

---

## 3. 反例：起点处理改变绕向或最终轮廓

### 3.1 反例 1：`ReverseContourPointPen` 反转全离曲线轮廓 —— 绕向与隐含起点同时改变

`ReverseContourPointPen._flushContour`（`pointPen.py:491-539`）对闭合轮廓先 `contour.append(contour.pop(0))` 再整体 `reverse()`，使"第一个点仍是第一个点"。对全离曲线轮廓，源码注释承认没有 on-curve 点可锚定：

```python
if firstOnCurve is None:
    # There are no on-curve points, be basically have to
    # do nothing but contour.reverse().
    lastSegmentType = None
```
（`pointPen.py:516-519`）

效果（测试 `test_quadNoOnCurve`，`Tests/pens/pointPen_test.py:499`）：

```python
# 输入： (0,0) (0,100) (100,200) (200,200)，全部 off-curve
# 输出： (0,0) (200,200) (100,200) (0,100)，全部 off-curve
```

- **绕向反转**（这正是该类在 `DecomposingPointPen(reverseFlipped=...)` 中补偿负行列式变换的用途，`pointPen.py:644-656`）；
- **隐含起点改变**：输入的隐含起点是 `(200,200)`-`(0,0)` 的中点 `(100,100)`，输出则变成 `(0,100)`-`(0,0)` 的中点 `(0,50)`——尽管第一个存储点都是 `(0,0)`。填充区域相同，但遍历方向相反、隐含起点落在不同的边上。

相关现状：`DecomposingPointPen` 的 `reverseFlipped` 提供 `KEEP_START` 与 `ON_CURVE_FIRST` 两种模式（`pointPen.py:44-54`），后者再套 `OnCurveFirstPointPen`（`filterPen.py:388-417`）把起点旋转到第一个 on-curve 点；测试见 `Tests/pens/filterPen_test.py:326-381`。对**全离曲线**轮廓，`ON_CURVE_FIRST` 找不到 on-curve 点，退化为纯反转——这一退化路径目前没有专门测试（缺口，见 §4）。

### 3.2 反例 2：全离曲线 blob 的重复首末点 —— 两条笔路径给出不同轮廓（issue #4014 的遗留缺口）

构造：二次 blob 的最后一个离曲线点与第一个相同：

```python
qCurveTo((10,20), (20,20), (20,10), (10,10), (10,20), None); closePath()
```

- **点笔路径**（`SegmentToPointPen` → `TTGlyphPointPen`）：`SegmentToPointPen.closePath` 只在首末点皆 on-curve 时去重（`pointPen.py:357-362`，注释明确引用 issue #4014："for quad blobs (all off-curve) every point must be preserved"），**5 个点全部保留**。测试 `test_quad3`（`Tests/pens/pointPen_test.py:285`）锁定此行为。
- **段笔路径**（直接 `TTGlyphPen`）：`TTGlyphPen.closePath` 的去重只比较坐标、**不检查 flag**（`ttGlyphPen.py:243-245`），末点 `(10,20)` 被弹出，**只剩 4 个点**。

两条路径对同一逻辑轮廓产生不同的 glyf 点列，而且差异**不是** §2 那种几何等价：丢掉重复的离曲线点后，原本 `(10,10)→(10,20)→(10,20)…(首点)` 这一对的隐含中点消失，闭合边改由 `(10,10)` 直接连回首点 `(10,20)`，隐含起点从 `(10,20)`（重复点自对中点）/ `(10,15)` 的配对关系改变，轮廓少了一段、最终形状不同。以上段笔行为已用本仓库 `Lib/` 下的 `TTGlyphPen` 实测确认（4 点 vs 5 点）。

**现状**：#4014 的修复（提交于 `SegmentToPointPen.closePath`）只覆盖了点笔适配器；`TTGlyphPen.closePath` 的坐标去重对全离曲线 blob 仍然不安全。**推断**：通过段笔协议直接绘制（而非经 `SegmentToPointPen`）的全离曲线、首末离曲线点重合的轮廓会被静默改变几何；实践中此类轮廓多由 UFO/点笔管线产生，故该缺口较少被触发。

---

## 4. 现状 / 推断 / 缺口汇总

**现状（有源码与测试双重支撑）**

1. 全离曲线二次轮廓的隐含起点 = 首末存储点中点，由 `BasePen.qCurveTo(None)` 显式算出并 `moveTo`（`basePen.py:379-384`）；全离曲线三次轮廓由 `Glyph.draw` 自行算中点并 `moveTo`（`_g_l_y_f.py:1620-1623`）。
2. `Glyph.draw` 对含 on-curve 的轮廓先旋转再 moveTo（`_g_l_y_f.py:1640-1647`）；`drawPoints` 为保点索引不旋转，全离曲线三次轮廓抛 `NotImplementedError`（`:1713`）。
3. 末尾 lineTo 被 closePath 隐含而省略（`_g_l_y_f.py:1650-1654`；`pointPen.py:262-277`），重复末点默认被 `TTGlyphPen.closePath` 删除（`ttGlyphPen.py:238-245`）。
4. 轮廓旋转（§2.2）与 implied on-curve 点删除（§2.3）是几何等价变换，均有测试锁定。
5. 反转全离曲线轮廓会同时改变绕向和隐含起点（§3.1，`test_quadNoOnCurve`）。

**推断（源码可读出的结论，无直接测试）**

1. `TTGlyphPen.closePath` 的坐标去重不检查 on-curve 标志，对首末离曲线点重合的 blob 会改变最终轮廓（§3.2，已实测确认行为，但仓库内无对应测试）。
2. `_is_mid_point` 的取整分支（`_g_l_y_f.py:1764`）意味着被 `dropImpliedOnCurvePoints` 删除的点重新隐含时可能与原点相差取整误差——对非整数坐标，"删除-重隐含"不保证逐点可逆。
3. 嵌套复合被分解时，隐含起点按分解后轮廓的存储顺序重新推导；`reverseFlipped=ON_CURVE_FIRST` 作用于全离曲线组件时退化为纯反转，起点选择不受控。

**缺口（测试或实现缺失）**

1. 无测试覆盖 `TTGlyphPen`（段笔）直接绘制首末离曲线点重合的全离曲线轮廓——§3.2 的几何改变不会被任何测试捕获。
2. `ReverseContourPointPen` 对全离曲线轮廓只有 `test_quadNoOnCurve` 一个测试，且未断言隐含起点的落点；`ON_CURVE_FIRST` 模式对全离曲线轮廓的退化行为完全无测试。
3. `TTGlyphPen.closePath` 与 `SegmentToPointPen.closePath` 的去重规则不一致（前者不看类型、后者看），没有测试约束两条路径对同一输入产生相同点列。
4. `drawPoints` 不支持全离曲线三次轮廓（`NotImplementedError`），点笔管线遇到此类 glyph 只能回退 `draw()`，放弃点索引稳定性——这是协议层面的已知限制而非 bug，但值得在文档中明示。

---

*本报告仅为源码分析，未修改仓库任何文件。*
