# loomerto 的定位规则与「文件模式」位置参数左移

配套 SKILL.md 的硬规则 1 / 5 / 6 与「改包的固定动作」第 3 步。

## 1. 定位一份 plan 的顺序（包里不推断，调用方说清）

| 顺序 | 形式 | 谁用 | 命令里写 slug 吗 |
|---|---|---|---|
| 1 | `--plan <plan 数据文件>`（= `$LOOMERTO_PLAN_FILE`；给目录则取其中的 `plan.json`） | 只处理一份 | **不写**（位置参数整体左移） |
| 2 | `--plans-root <目录>`（= `$LOOMERTO_PLANS_ROOT`）或薄壳塞的 `EMBEDDED_PLANS_ROOT` | 一份库里有好几份 | 要写 |
| 3 | 当前目录的 `plan.json`（存在才认，等价于 `--plan ./plan.json`） | 人就在数据目录里 | 不写 |
| — | 都没有 | — | 退 2，并把上面三条与 `plan new` 的用法一起打印出来 |

- 数据文件**叫什么名字都行**（`mine.json` 也可以）；`plan.json` 只在「一个数据目录」里是那个唯一固定名。
- 三个派生视图（`PLAN.md` / `plan.html` / `plan.canvas`）与数据文件**同目录** ⇒ `plan_dir()` 必须由
  「解析后的数据文件路径」取父目录，`save()` 也要写回那条路径。
- 「只认一份」的判据（`file_mode()`）：给了 `--plan` / 同名环境变量 ⇒ 是；给了 `--plans-root` ⇒ 否；
  都没给 ⇒ 看当前目录有没有 `plan.json`。**显式给的库优先**：给了库就不该被当前目录的 `plan.json` 抢走。
- `list` 也要分两种情况：给了 `--plan` 就只列这一份，否则列 `--plans-root` 库里的全部；
  两个都没给时打印「该给哪个旗标」而不是空列表。

## 2. 让 slug 可以省：位置参数统一左移（别给每个子命令写两套解析）

做法：**所有**位置参数声明成 `nargs="?"`（`slug` 默认 `""`，其余默认 `None`），每个子命令登记
「slug 之后还有哪几个位置参数」（`shift=["ref", "status"]` 这种），在入口 `main()` 里统一处理：

1. 文件模式下，把 `[slug] + shift` 这些格子的值**整体左移一位**给 `shift`，`slug` 清空后从数据文件取
   （`plan.json` 的 `slug` 键，读不到就取目录名）；
2. **多写了**（最后一个 `shift` 格子非空 ⇒ 用户还按老写法把 slug 写上了）⇒ 退 2，打印「文件模式下不要再写
   slug」+ 这个命令的正确形状；
3. **少写了**（`shift` 里有 `None`）⇒ 退 2，打印这个命令要哪几个参数。**这一格允许空**时，要把它的名字
   登记进 `set_defaults(..., optional=[…])`：目前有两格 —— `block set_status … --unset`（状态不动、
   只清线程登记）与 `block set_<属性> <ref>`（不给值 = 清空那一格）。不登记就会被判成「少写了」；
4. 非 `plan new` 的命令里给了 slug、又与数据文件的 slug 不符 ⇒ 退 2（别静默拿它去定位）；
5. `plan new` **不左移**：它的位置参数就是「新 plan 的 slug」，可以省（省了取目录名）。

坑：`shift` 为空的子命令不要顺手把 `slug` 清空 —— 那会让「还想写 slug」的调用静默丢参数。
坑：**`nargs="*"` / `nargs="+"` 的格子不能进 `shift`** —— 定长左移只对「一格一个值」成立，可变长会把位置
参数吃进列表里、整条命令整体错位。要收多个值就换形状：**一条判据一个位置参数**（`set_audit` 就是
`block set_audit <ref> <判据1> <判据2> …`，参数里的 `;` 仍算分隔）或者改成可重复的旗标（`--deps` / `--add`），
别指望左移能配合 `nargs="*"`。
坑：`--unset` 这类旗标与位置参数混排时 argparse 会先吃位置参数（`block set_status <ref> --unset running` 会变成
「unrecognized arguments: running」）—— 这是 argparse 的脾气，不是我们的 bug；文档里给正确形状即可。

### 2.1 跨组错用给人话错误（不是 usage）

`task set_status/remove/show` 与 `block set_status/remove/show` 各自 `find()` 完之后**先看对象类型对不对**，不对就 `die()` 一行
人话 + 该用哪个命令（例：`T-001#B-001 是块不是任务 —— 块状态用 block set_status …；任务状态用 task set_status …`）。
`block expand` / `block compress` 互为逆操作，也照这个写法互相指路。**别让它落到模型层的
「找不到块 X」** —— 那看着像数据坏了。

## 3. 改定位旗标 / 命令面的验收矩阵（两条模式都要真跑）

```bash
D=/tmp/lt-acc; P=$D/p.json
loomerto --plan $P plan new acc --title x                     # 落点必须显式
loomerto --plan $P task add --title t                            # 文件模式下 task add 不吃位置参数
loomerto --plan $P task set_status T-001 running --by me
loomerto --plan $P task show T-001 | task remove T-001 --force
loomerto --plan $P block add --task T-001 --title b --doc d --done-when c --status pending
loomerto --plan $P block insert T-001#B-001 --after --title 插一步 --done-when x --dry-run
loomerto --plan $P block set_status T-001#B-001 running --by me --delegation deleg_x
loomerto --plan $P block set_status T-001#B-001 --unset      # 允许省略 <状态> 的写法
loomerto --plan $P block set_title T-001#B-001 "新标题"       # 一条属性一条命令（set_doc/type/input/… 同形）
loomerto --plan $P block set_audit T-001#B-001 跑通 有结论      # 一条判据一个位置参数；不给值 = 清空
loomerto --plan $P block assign T-001#B-001 --to you
loomerto --plan $P block deps T-001#B-001 --add T-002#B-001
loomerto --plan $P block move T-001#B-001 --task T-002
loomerto --plan $P block expand T-001#B-002 --step "第二步 :: 做 B :: 判据B"
loomerto --plan $P block bypass T-001#B-002                 # 摘掉中间块、前后直接接起来
loomerto --plan $P block compress T-002 --keep-task --force
loomerto --plan $P block remove T-001#B-003 [--force]
loomerto --plan $P block show T-001#B-001 | task show T-001
loomerto --plan $P current | check | workers | render | list | note "记一句" | digest --to you
loomerto --plan $P block show                                 # 退 2：缺参数
loomerto --plan $P block show acc T-001#B-001                 # 退 2：多写了 slug
loomerto --plan $P block set_status T-001#B-001 done --delegation d  # 退 2：状态闸（done 不收 --delegation）
loomerto --plan $P block set_status T-001#B-001 nope          # 退 2：「状态只能是 […]」（不是 KeyError）
loomerto --plan $P block set_type T-001#B-001 nosuch          # 退 2：类型闸（只收 KINDS）
loomerto --plan $P block set_doc T-001#B-001 "一样的话"        # 退 2：没变化（一个字不写）
loomerto --plan $P task set_status T-001#B-001 done             # 退 2：这是块不是任务
loomerto --plan $P block new  --task T-001 --title x          # 退 2：旧名（new/set/rm/describe/collapse）
loomerto --plan $P task add T-001 --title t                     # 退 2：旧名（task new/set/rm）
loomerto --plan $P move T-001#B-001 --task T-002              # 退 2：顶层 move 已不存在
cd /tmp/empty && loomerto current                             # 退 2：打印该给什么
loomerto --plans-root <真实库> list && loomerto --plans-root <真实库> block show <slug> <ref>
plan --plan $P list                                           # 第二个入口名
cd <repo> && python3 -m loomerto --plan $P current             # 模块入口（仅仓库根可用）
loomerto --help | grep -c profile                             # 删过旗标 ⇒ 必须为 0
```

- 文件模式要**逐条**跑 **34 个叶子命令**（`plan new` / `task add|set_status|remove|show` /
  `block add|remove|insert|bypass|expand|compress|show|deps|assign|move` /
  `block set_type|set_title|set_doc|set_status|set_input|set_output|set_command|set_audit` /
  `note|digest|render|check|current|workers|list|open`）：
  左移是在入口统一做的，漏登记一个子命令的 `shift` 得到的是**参数错位**（静默跑在错的对象上），不是报错 ——
  只有真跑才发现。`set_*` 这一族全是 `shift=["ref","value"]` + `optional=["value"]`，**随便挑一条跑一遍不够**：
  它们是同一张表生成的，但 `attr` 是逐条 `set_defaults` 给的，跑一遍能同时验证表和分派。
- `--dry-run`（`block insert` / `block expand` / `block compress`）要**比落盘 sha**：跑完 `shasum -a 256 $P`
  必须一字不变（它们是改内存副本 + 不 commit）。
- 跑完看产物：数据文件同目录应有 `PLAN.md` / `plan.html` / `plan.canvas`，且 `plan.json` 的 `slug`
  与目录能对上。
- 真数据回归一律**只读**命令；回归命令不要接 `| tail -1`（收尾行常是空行，会把结论吞掉）。

### 3.1 跑矩阵的三个现成形状（取旧版 / 断言器 / 子命令自检）

```bash
# ① 取「改动前」那份代码：不用 git worktree（不占坑、不污染分支登记表）
OLD=$(mktemp -d); (cd <repo> && git archive <旧 sha>) | tar -x -C "$OLD"
(cd "$OLD" && python3 -m loomerto --plans-root <真实库> list) > /tmp/old.txt   # 必须 cd 进去（-m 看 cwd）
(cd <repo> && python3 -m loomerto --plans-root <真实库> list) > /tmp/new.txt
diff -u /tmp/old.txt /tmp/new.txt      # 只读输出：命令面重排不该动它，动了就是改坏了

# ② 期望退出码的断言器（矩阵里一条命令一行，跑完一眼看出哪条红）
L="loomerto --plan $P --no-render"     # 这变量展开成多个词，靠 "$@" 接住
ck() { local want=$1 desc=$2; shift 2; "$@" >/tmp/o 2>/tmp/e; local got=$?
       [ "$got" = "$want" ] && echo "ok [$got] $desc" \
         || { echo "FAIL [$got want $want] $desc"; head -3 /tmp/e; fail=1; }; }
ck 0 "block add" $L block add --task T-001 --title A --status pending --done-when x
ck 2 "旧名"      $L block new --task T-001 --title x

# ③ 子命令自检（闸①）：每个叶子都得挂着可解析的 f=
PYTHONPATH=<repo> python3 -c '
from loomerto.cli import _parser
ap = _parser(); sub = [a for a in ap._actions if a.dest == "cmd"][0]
leaves, bad = [], []
def walk(p, pre):
    kids = [a for a in p._actions if a.dest == "sub" and isinstance(a.choices, dict)]
    if not kids:
        leaves.append(pre)
        f = p._defaults.get("f")            # set_defaults 落这里，不在 _actions 里
        if not callable(f): bad.append((pre, f))
        return
    for k, sp in kids[0].choices.items(): walk(sp, pre + " " + k)
for k, sp in sub.choices.items(): walk(sp, k)
print(len(leaves), bad); assert not bad'
```

坑：断言器的 `shift` 位数是 **2**（want + desc）。写成 `shift 3` 会把 `loomerto` 也吃掉，每条命令都变成
`--plan: command not found`（退出码 127）—— 看着像包坏了，其实是测试脚本自己错位。

## 4. 改完拉平副本（否则下一次会话按旧副本办事）

```bash
cp   <repo>/skills/<cat>/<name>/SKILL.md    <profile>/skills/<cat>/<name>/SKILL.md
cp   <repo>/skills/<cat>/<name>/scripts/*.py <profile>/skills/<cat>/<name>/scripts/
diff -rq <repo>/skills/<cat>/<name> <profile>/skills/<cat>/<name>   # 除 .DS_Store 外应为空
python3 -m py_compile <profile>/skills/<cat>/<name>/scripts/*.py
```

- **只在改动能被装好的 CLI 撑住时拉平**：包是 editable 装的（`~/.local/bin/loomerto` 指向某个 checkout），
  在 worktree 里改完、**还没合进那个 checkout 之前不要动 profile 副本** —— 否则 skill 里的
  新命令名会撞上旧 CLI，别的 bot 一用就报错。顺序永远是：合入 → 再拉平 → 再 `diff -rq`。
  **例外/更准的判据**：editable 装的是「主 checkout 当前那一支」，不是「main」。所以你**在主 checkout
  自己的分支上**改（`git worktree list` 第三字段就是那一支）时，装着的 CLI 已经跑的是新代码（拿真命令探一次
  即可证明），此时拉平是安全的 —— 但要在 `REQUIREMENTS.md` §4 记一句「副本与新命令名绑在**哪一支**上」，
  否则下一个人把主 checkout 切回 main，profile 副本就变成空头支票。
- 薄壳（`scripts/plan.py`）里「调用方自己给过就不补旗标」的判断要跟着新旗标改（判 `--plan` 与 `--plans-root`），
  否则薄壳会补一个多余旗标、包里多打一行「两个都给了」的警告。
