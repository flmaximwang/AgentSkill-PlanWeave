---
name: maintain-the-loomerto-package
description: "Use when 要改 loomerto 这个包（CLI 旗标、子命令、文档、需求）时用；含定位规则与验收矩阵。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [loomerto, package-development, cli, cross-harness, docs-discipline]
    category: loomerto
    related_skills: [loomerto-plan, loomerto-check-commands, author-a-skill-in-a-pack-repo]
---

# 改 loomerto 这个包（代码 / CLI / 文档 / 需求）

## When to Use

- 用户说「loomerto 支持这个功能吗」「给一个 cli 入口」「加一个子命令」「这个旗标是干嘛的」——要**改包**或
  按包的现状回答。
- 要动 `/Users/maxim/Repositories/Repo/Loomerto` 里的 `loomerto/*.py`、`docs/`、`REQUIREMENTS.md`、`skills/`。
- **不属于**：用这个工具去维护一份 plan（改状态 / 派活 / 发提醒 / 看图）→ `loomerto-plan` 那一族
  （族里另有 `loomerto-remind` / `loomerto-check-commands` / `loomerto-check-temps` / `loomerto-intake`）；
  把包仓库当「发 skill 的包」来写 skill 的通用流程 → `author-a-skill-in-a-pack-repo`（本 skill 只补它没有的
  包本体约定）。

## 硬规则（用户拍板，不许自行回退）

1. **一份 plan 在哪，永远由调用方说清**（包里不猜、也没有默认 harness 目录）：
   `--plan <plan 数据文件>`（= `$LOOMERTO_PLAN_FILE`；给目录也行）→ `--plans-root <目录>` + `slug`
   （= `$LOOMERTO_PLANS_ROOT`）→ 当前目录的 `plan.json`（存在才认）→ 都没有就**退 2 并把该给什么打印出来**。
   两个旗标都给时按 `--plan` 算（打一行 ⚠）。`new` 必须显式说落点。
2. **包里不许出现 profile / hermes / 任何 harness 的目录假设** —— 用户的原话是「不要支持 profile，
   我从来没有定义过 loomerto 就是给 hermes 用的」。所以：没有 `--profile`、没有 `$LOOMERTO_PROFILE`、
   没有 `plans_root()` 里推断 `~/.hermes/...`、没有按 profile 拼转录路径的助手（`hermes_home()` /
   `live_root()` / `transcript_path()` 这类一律不进包）。Hermes 侧的路径约定（plans 库位置、
   `cache/delegation/live/<deleg>/task-<n>.log`）写在 **Hermes 侧的 skill / 薄壳**里，由它显式传给包
   （例：`exec … --transcript <路径>`）。**这条是定位级约定**：只要包里留下一条 harness 假设，下一条就会跟进去。
3. 纯 stdlib、零依赖、`requires-python >= 3.9`；`plan.json` 是唯一真相，`PLAN.md` / `plan.html` /
   `plan.canvas` 永远是派生物（原子落盘）；**所有写入过 `store.commit()`** 一处。
4. 分层不许串：`model`（纯函数、不 print 不 exit、抛 `PlanError`）/ `store`（磁盘 + 唯一写入漏斗）/
   `render`（只返回字符串）/ `workers`（只读文件）/ `cli`（**唯一的 print 与退出码**）。
5. 文件模式（给了 `--plan`）下 **slug 可以省**：命令的第一个位置参数本来是 slug，此时位置参数**整体左移一位**
   （`block set_status <ref> <状态>` / `block set_<属性> <ref> <值>` / `task set_status <ref> <状态>` /
   `block show|remove|insert|bypass|move|expand|compress|deps <ref>` / `task show|remove <ref>` / `note <text>`）；
   多写一个 slug 退 2 并点明。**允许留空的格子**要在 `set_defaults(..., optional=[…])` 里登记：
   `block set_status … --unset` 不带状态、`block set_*` 只给 ref 不给值（= 清空那一格）——
   `_apply_file_mode` 的「少写了」检查会跳过 `optional` 里的 dest；不登记就会把合法的「留空」判成缺参数。
   **`nargs="*"` 的格子（如 `--deps` / `--add` / `set_audit` 的判据）不能放进 `shift`**：定长左移靠
   `getattr(a, d) in (None, "")` 判「这格空没空」，而列表**永远不等于 `None`** ⇒ 合法的「只给 ref、
   值留空」会被判成缺参数。这类命令**不走 `shift`**（在 `_SET_ATTRS` 里把键记进 `_NO_SHIFT`），
   在 `_apply_file_mode` 里单独给一段：把 `slug` 还成 `ref`、把 `ref` 并回 `value`，再清 `slug`
   （argparse 对 「`?` + `?` + `*`」是**贪心**的 —— 位置参数 ≥3 时第一格落 `slug`、第二格落 `ref`、
   其余全进 `value`，所以并回去的顺序别搞反）。命令仍要声明 `slug` 那一格，`value` 的默认值
   给 `[]` 而**不是** `None`（`cmd_*` 里 `a.value or []` 才稳）。
6. **`set_status` 一个入口管「状态 + 身份」，参数按状态卡**：`edits.BLOCK_SET_FLAGS` / `TASK_SET_FLAGS` 是唯一那张表
   （在途状态才收 `--by`/`--delegation`/`--task-index`/`--transcript`，`--artifact` 只在 `done`），
   命令层 `_apply_set` 先调 `check_set_flags` 再落 `set_status` —— 加状态或加旗标时**只改那张表**，
   命令与画布（`serve.py` → `set_status`）同受约束。状态本身不合法时 `check_set_flags` 要**直接返回**
   （让 `set_status` 报「状态只能是 […]」），不然 `table[status]` 会 KeyError。
   **其余属性一条命令一个**（`block set_title|set_doc|set_type|set_input|set_output|set_command|set_audit`）：
   形状统一 `block set_<属性> <ref> <值>`，全部走 `edits.set_field` 一处。加一条新属性 = ①
   `model.BLOCK_FIELDS` 加键（若还没有）② `cli._SET_ATTRS` 加一行（命令名那截 → 键 + 说明）③ 在
   `_parser()` 的 block 组里按想要的顺序加一句 `_add_set_attr(g, "<名字>")` —— 别再照抄一份 parser。
   值**整组替换**、留空 = 清空（标题除外），**没有变化 ⇒ 退 2 且一个字不写**（与 `set_deps` 同一纪律）。
7. 退出码：参数错 / 找不到对象 → **2**；`check` 有图错误 → **1**；`workers` 见 ⚠/❌ → **1**；其余 → 0。

## 改包的固定动作

1. **认门**：`cd /Users/maxim/Repositories/Repo/Loomerto && git status --short` 看有没有别人的在途改动
   （这套仓库常有别的会话在写）；包是 **editable 装**的（`uv tool install --editable <repo>` → 
   `~/.local/bin/{loomerto,plan}`），所以**改完代码立刻生效，不用重装**。
2. **改代码**：按上面第 4 条分层放。新的定位/派生逻辑先想清楚它属于哪一层（路径解析归 `store`，
   图/派生状态归 `model`，只有参数解析与打印归 `cli`）。
3. **真跑验收**（不许只看 diff）：文件模式与库模式**两条都要跑**，文件模式下**逐条**跑完 **34 个叶子命令**
   （= 31 条真命令 + `info`×2 / `threads` 三个别名；`plan new` / `task add|set_status|remove|show` /
   `block add|remove|insert|bypass|expand|compress|show|deps|assign|move|set_type|set_title|set_doc|set_status|set_input|set_output|set_command|set_audit` /
   `note|digest|render|check|current|workers|list|open`），再对**真实数据**做只读回归（`--plans-root <真实库> list / current / check / workers`）。
   改过名字的**每一组**都要扫旧名退 2（`block` 五个 + `task` 三个），别只扫刚动手的那一组。
   矩阵与边界用例、以及跑矩阵的三个现成形状（取旧版 / 断言器 / 子命令自检）见
   `references/loomerto-cli-location-and-cli-conventions.md` §3 与 §3.1。
   - **闸① 的子命令自检读 `parser._defaults["f"]`**：`set_defaults(f=…)` 落在 `_defaults` 里、**不是**一条
     action —— 遍历 `p._actions` 找 `f` 会把每个叶子都判成「没挂处理函数」（一片假红，白查一轮）。
     顺带**断言叶子总数**：不写这个数，改了命令面之后自检会假装通过。
   - **闸④/⑤ 起画布服务要 `PYTHONUNBUFFERED=1`**：`print` 到重定向文件是**块缓冲**的，后台起服务后那行 URL
     还压在缓冲区里、从日志里抽不出来，看着像「服务起不来」。`PYTHONUNBUFFERED=1 loomerto --plan <P> open --port 0 --no-open >log 2>&1 &`
     → `sleep 2` → 从 log 取 URL → `curl` 回读页面。**改页面资产不用重启服务**（每次 `GET /` 从磁盘重读），
     改 `serve.py` 才要重启；纯文字改动也要回读一次页面并数一遍反引号是否成对 —— 提示文字就嵌在模板字面量里。
4. **文档对齐**：`docs/cli-reference.md` 是**从 `argparse` 取出来的现状清单** —— 改了命令就必须改它，
   并把顶部那行**代码基线 sha** 换成这次代码提交的 sha；`docs/architecture.md` 里的跨 harness 约定
   （定位顺序、薄壳契约、验收四道闸）同步改。
5. **需求**：`REQUIREMENTS.md` 是**需求单一入口** —— 条目**只在用户明确说了或拍板之后**才增删，
   实现状态变了只改「现状」列、不新开一份清单。
6. **skill 与副本**：仓库里的 `skills/**/SKILL.md` 与 `scripts/plan.py` 薄壳是发布源；改完把
   `default` profile 的**已装副本**也拉平，并 `diff -rq <repo 目录> <profile 副本目录>`（除 `.DS_Store`
   外应为空）。薄壳里「调用方自己给过旗标就不补」的那段判断要跟着新旗标改。
   **副本可能比仓库源「新」**（别的会话直接把段落写进 profile 副本，仓库那份还没回移植）：动副本前先
   `diff <repo>/SKILL.md <profile 副本>/SKILL.md` **看方向**，别整份 `cp`（那是把别人写进副本的段落抹掉）——
   把同一段改动**分别打在两份上**，再把「副本先行、diff 不为空是预期的、拿什么判据代替」写进
   `REQUIREMENTS.md` §4 的拉平记录。判据用「两份各出现几处新标识」（如 `grep -c "block deps"`），不是 diff 为空。
   **回移植前先核这条差异是不是「分支限定」的**：装好的 CLI 跑的是主 checkout 当前那一支，副本里可能写着
   只活在**别的特性分支**上的命令 —— 拿**装着的 CLI** 直接探一次那条命令（例：`loomerto block deps …`
   回 `error: invalid choice: 'deps'`）就能判；探不到就别把 B 支的文档搬进当前这支（那是把「别人分支上的
   功能」写成当前分支的现状）。
7. **提交分两个**：代码一个（`feat(...)`），文档 / 需求 / skill 一个（`docs:` 且信息里写明代码基线 sha）——
   基线 sha 只有在代码提交之后才存在。**不推远端，除非用户说**。
8. **用户说「把现在几个 feature 合并到 main 再推」时**：先给分支分档 —— `git rev-list --left-right --count main...<分支>`，
   两边都是 0 = 同一支；左 N 右 0 = main 领先（祖先，什么都不用做）；左 0 右 N = 可**快进**（`git merge --ff-only`）；
   两边都不为 0 = 真合并（`git merge --no-edit`，冲突集中在 `REQUIREMENTS.md` 编号 / README / docs / skill 正文）。
   合并前在每个 worktree 里 `git status --short` 确认没人在写。合完 **`main` 就是「装好的 CLI 现在跑的那份」**
   —— 那些「只活在特性分支上的命令」（如 `block deps`）要到合进 main 才对真机可用，profile 副本里的对应文档
   也才不再是空头；接着按第 6 条恢复拉平，再按用户指示推 `origin/main`。

## 改**命令面**（改名 / 重排 / 加一条命令）

用户说「重排一下 block 的命令顺序与名称」这类话时，改 parser 只是开头 —— 命令名是**跨文件的主键**：

1. **先问清「这份列表是全部还是增量」**：用户给一串名字时，「没被点到的命令怎么办」有三种走法
   （原样保留 / 保留但挪位置 / 删掉），差别很大且不可从列表本身推出 —— 一次问清，别猜。同时问清**旧名要不要留别名**
   （本仓库的规矩：**旧名一律退 2，不留别名**，旧行为靠 `argparse` 的 `invalid choice` 报出来）。
   **一个决策往往不止一轮**：用户先丢一份列表、随后又追一句改口（「都做」/「继续拆」这类）时，**改原来那条需求条目的
   「现状」列**，不要新开一条 —— 需求条目只在用户拍板后增删，而这是同一条需求的追加拍板。改口常常同时扩大范围
   （例：原本写「另一组命令原样不动」，回头变成跟着一起改名）—— 那也要把**那一组**的旧名扫进退 2 的用例里，
   否则「原样不动」那句话会留在文档里变成假话。
2. **代码面只动两处**：`cli._parser()` 里那一组 `add_parser` + `set_defaults`，和命令函数名（`cmd_block_*`）。
   分派靠 `set_defaults(f=…)`，**改名字不影响分派**；真正会漏的是**错误提示里的字面量**
   （`grep -n "block <旧名>" loomerto/*.py`，跨对象指路的那几行最容易漏）。
3. **消费者清单要扫全**（改名前先跑一遍，按命中行数排序，别漏）：
   `docs/cli-reference.md`（现状清单，改名后必须重取底稿）、`docs/architecture.md`、`docs/canvas-sync.md`、
   `README.md`、`REQUIREMENTS.md`（§3 摘要 + 新增一条需求）、`loomerto/assets/*.html`（画布里的提示文字）、
   `skills/**`（**仓库源与 default profile 副本两份**）、`blind-tests/`、以及**本 skill 自己的
   `references/`**（里面的验收矩阵与边界用例就是一串命令）。
   扫法：`grep -rn "<旧名>" docs README.md REQUIREMENTS.md skills loomerto`，**不要** `grep -r` 整个 profile 目录
   （里面有几十 MB 单行 JSON，会挂到超时）。
4. **对拉判据**：改名轮里「改前 vs 改后」**不能**拿 `--help` 的子命令表当判据（那本来就是改动本身）；
   要拿**真实库的只读命令逐字节对拉**（`list` / `current` / `check` / `workers` × 每份 plan，见
   `references/loomerto-cli-location-and-cli-conventions.md` §3）—— 命令面重排**不该改变任何只读输出**，
   这一条变了就是改坏了。旧名各跑一次，退出码必须是 2。
5. **新属性一条命令一个**（见硬规则 6 的第 2 段）：别把七个 `set_*` 写成七份复制粘贴的 parser，
   用 `cli._SET_ATTRS` + `_add_set_attr()` 一张表生成 —— 下一轮「再加几个属性」只改那张表。
6. **skill 脚本打印出来的命令也是交付面**：check 这类 skill 的脚本会打印「照抄就能修」的命令 —— 改名漏了它，
   用户拿到的是一条**跑不通**的补法（比漏改文档更坏：文档只是过时，它会当场报错）。改完要**真跑那个脚本**、
   把输出里那条建议命令照抄执行一次，通了才算改完；只 grep 到文件名就收工不算。

## 出版面：改 skill 名 / 改 description

- **改 skill 名（slug）是一次「必须推远端」的批量重组**，不是 `mv` 个目录：`hermes skills install` / `update`
  按标识符（`<owner>/<repo>/skills/<类目>/<名>`）**回远端取件**，本地 `git mv` 出来的新名字装不回来
  （`install` 只吃 hub 标识符或**单个 SKILL.md 的 URL**，没有本地目录入口 ⇒ 带 `scripts/` / `references/`
  的 skill 靠 URL 也装不全）。把代价链按这个顺序摆给用户，拿到答复再动手：① 仓库 `git mv` + frontmatter
  `name:` + README / REQUIREMENTS / docs / 兄弟引用（几十处，机械改）；② **推远端**（= 把当前分支所有在途
  提交一起发出去，要用户点头 —— 这仓库常态就是「本地领先远端二十来个提交」）；③ 卸载旧名 + 装新名
  （`--category` 只在安装时读），再 `diff -rq` 回读。「只在仓库里改好、副本留旧名」= 仓库与 profile 不一致，
  除非用户明确要这样，否则别默认。提改名方案的动因通常是**可发现性**（agent 想到「用 <包名>」时，按包名
  前缀能在上百条 skill 里一次找齐同族）—— 把这条理由和「现名 → 新名」的对照表一起给。
- **往 description 尾部追加钩子不动路由窗口，因此不用跑盲测**：判据是**前 57 字符逐字不变** —— 拿新旧
  两条做字符串切片比一次（别眼看）；要动窗口里面（哪怕挪一个词）才按 `skill-routing-blind-test` 跑一轮。
- **指令性内容落 SKILL.md 正文的具名小节，描述位只放一行钩子**：描述会被截断、也不该承载流程。同族 skill
  用一行「见 `<核心 skill>` 的「<小节名>」」指过去，别把同一段在这族里抄五遍。
- **这一族现在的名字（引用一律用新名）**：`loomerto-plan`（旧 `maintain-a-shared-plan`）· `loomerto-remind`
  （旧 `remind-collaborators`）· `loomerto-check-commands`（旧 `check-plan-node-commands`）· `loomerto-check-temps`
  （旧 `check-plan-temp-hygiene`）· `loomerto-intake`（旧 `intake-a-running-collaboration`）。改名后**立刻扫一遍
  别处指向旧名的引用**（`grep -rl <旧名> …` 排除 `blind-tests/` 与 `.git/` 应全为空）——本 skill 自己就在
  When to Use 与 `related_skills` 里指过旧名；执行配方（git mv → 引用改写 → 卸载/重装 → 回读）见
  `author-a-skill-in-a-pack-repo` 的「改名一条已发布的 skill」。

## 「按对象拆 module / 重构包结构」这一类请求

用户说「把 plan / task / block 的定义与操作分 module 保存」「能不能整理成一个 class」「让整套代码更容易查看」时，
先查清楚**定义与操作现在在哪**再谈拆法，别顺手就搬：

- **只有 block 的形状有声明**（`model.BLOCK_FIELDS`）。**plan 的键只在 `cli.cmd_new` 的字典字面量里、
  task 的键只在 `edits.add_task` 的字面量里** —— 问「plan / task 是怎么定义的」，答案只能从建对象的那个
  函数里读出来，`model` 里找不到。回答这类问题时先给这两处的 `文件:行`。
- 对象清单（每个对象的定义在哪、操作落哪一层、以及**跨对象、按对象切不动的地方**）见
  `references/object-definition-and-operation-map.md`。函数名是主键、行号会漂：引行号前重跑
  `grep -n "^def " loomerto/cli.py` 与 `grep -n "^[A-Z_]* = " loomerto/*.py`。
- **「拆成对象模块」会动硬规则 4**（`model` 纯函数 / `edits` 唯一改动实现 要并进同一个对象模块，纯函数区与
  改动区同文件）—— 这条是用户拍板过的，**只能由用户重新拍板，不许自己放宽**；把它作为代价写进选项里，
  同时点明「`cli` 是唯一 print / 退出码」这一半保持不变。
- 这一族的选项空间就三档，别自造第四档：**拆模块**（两个大文件搬迁 + 全套验收重跑）/ **只给 plan、task 补形状
  声明**（照 `BLOCK_FIELDS` 的样子加 `PLAN_FIELDS` / `TASK_FIELDS` + `new_plan()` / `new_task()`，最小、不碰任何
  硬规则）/ **只出文档**（`docs/objects/<对象>.md`，代码不动）。
- **批量重组先获批准**（用户的规矩）：把现状表 + 三档代价问出去、拿到答复再动手；问之前先把只读的现状清单跑掉。

## 坑

- **新分支从哪起，先看「装好的 CLI 跑的是哪一支」**：包是 editable 装的，跑的就是主 checkout 当前所在的分支
  （`git worktree list` 第三个字段）。这个仓库常态是：`main` 落后于一条特性分支（如 B 档「块的形状收口」在
  `feat/block-schema`、`model` 里有 `BLOCK_FIELDS` / `new_block`，`main` 上**没有**）—— 从 `main` 起新 worktree
  会直接 `ImportError: cannot import name 'new_block'`。要「改完立刻能在装有工具的会话里试」，就**从当前装在跑的那支起**
  （`git worktree add -b feat/<名> <路径> feat/block-schema`），并在提交信息/文档里写清它依赖哪一支、还没合进 main。
- **这个包没有 `tests/` 目录**：验收按 `docs/architecture.md` §7 的「五道闸」**现场跑**（① 名字自检：静态查用到的名字能不能解析
  ② 对拉：与 `git show <旧 sha>:<路径>` 比 stdout/stderr/退出码与产出文件 ③ 真实库只读回归 ④ install + 薄壳回读
  ⑤ 前端改动要真浏览器拖一次），**不落成测试文件**（别自创 `tests/`）；跑验收的脚本放 `$BH_AGENT_WORKSPACE` / 临时目录即可。
- **派生状态的规则不止一处实现**：`model.block_effective`（包）+ 仓库 `loomerto` 包里 `assets/` 下那份看板模板的内联 `eff()`
  （看板内联 JS 自己算一份）+ `canvas.html` 里解释派生原因的那段。动「派生状态」的定义必须三处一起改，
  否则看板与画布会各显示一套。**改完还要重渲真实 plan 的派生视图**（`loomerto --plans-root <库> render <slug>`）：
  `plan.html` 里嵌着它自己那份 JS，不重渲的话旧文件会一直按旧规则显示（`plan.json` 一个字节都不会变 ——
  重渲只写 PLAN.md / plan.html / plan.canvas，可以拿渲染前后 `plan.json` 的 sha 证明这点）。
- **「状态 × 负责人」的单一来源 = `model.STATUS_OWNER`**（三档 never/required/may）：`待认领` 不能有负责人
  （定义就是「还没人接」）—— 所以 `pending` + 依赖就绪时，**有 `owner` 派生为 `claimed`（已认领）**、
  无 `owner` 才是 `ready`；`等前置`/`待批准` 可以有 owner（先派活、写「等谁点头」）。改这条要有心理准备：
  真实库里凡是「早就派好 owner、依赖又已就绪」的块，显示状态会整批从 待认领 变 已认领 —— 先拿真数据
  逐份对拉（旧 vs 新 `current` / `check` / `workers`）再落，别拿一块自造的 plan 就宣布改好了。
- **「在途」要按存储状态判，不能按派生状态判**：派生出来的「已认领」没有开工时刻（`status_since` 还是
  当初置 `pending` 那一刻）、也没登记线程 —— 拿它进 `stale_blocks` / `workers` 只会误报。这两处改回
  `b["status"] in ACTIVE`（存储）之后，真实库的告警面就与改前逐字节相同。
- **命令面按对象分组是这个包的定局**：一级名字只留 `plan` / `task` / `block`（分组）+ `note` / `digest` /
  `render` / `check` / `current` / `workers` / `list` / `open`。**新加一个动作时先问它作用在谁身上**：
  块的事进 `block`（`move` 就是这么从顶层挪进来的）。顶层再长出一个平铺动作，下一轮就得重排一遍。
- **另一个会话可能同时在 main 上推提交**：动手前 `git log --oneline -1 main` 记下基线；收工前再看一眼。
  真撞上了就在分支上 `git merge main` 解冲突（**别 rebase** —— 那会改写代码提交的 sha，而文档里「代码基线」
  引的就是那个 sha）。冲突处通常是：parser 段、`edits` 里新函数的位置、`REQUIREMENTS.md` 的编号
  （**新条目要接着 main 的最大号往下排**，我曾把 R-16 用重了）。
- **跑「另一份 checkout 的代码」用 `python3 -m` 必须看 cwd**：`-m` 把**当前目录**放在 `sys.path` 最前，
  在 main 的目录里给 `PYTHONPATH=<worktree>` 跑的还是 main 那份 —— 对拉会变成自己跟自己比。要么 `cd` 进
  那份 checkout，要么在没有 `loomerto/` 目录的地方跑；**先证明跑的是哪一份**（两份 `--help` 的子命令表必须不同）。
- **删 / 改一个旗标前先搜谁在用**：除了这个 clone，还要扫别的 profile 的 skill 正文与 cron
  （`search_files pattern="<旗标>" file_glob="*.md" path=<profiles 根>`）。**不要 `grep -r` 扫整个 profile 目录**：
  里面躺着几十 MB 的单行 JSON（curator 账本 / 缓存索引），实测挂到 180 s 超时还什么都拿不到。
- **`save()` 要写回「解析后的数据文件路径」**，不是 `<plan_dir>/plan.json`：数据文件叫什么名都行
  （`mine.json`），视图与它同目录；只改定位、忘了改写入，那份自定义名字的数据就会与它的三视图分家。
- **`shift` 为空的子命令（`current` / `check` / `workers` / `render` / `digest` / `list` / `task` / `block`）
  不要顺手清 slug**：那会让「还按老写法写 slug」的调用静默丢参数。
- **`python3 -m loomerto` 只在仓库根（或 `PYTHONPATH` 指过去）可用**，任何目录可用的是装好的 CLI
  （`loomerto` / `plan` 两个入口名）。换目录后 `No module named loomerto` 是正常的，不是包坏了。
- **块的形状只有一处声明 = `model.BLOCK_FIELDS`**（键 → 默认值/工厂）：加一个块级键就改它一处 ——
  `model.new_block()` 是建块的**唯一**字面量（`edits.add_block` / `edits.insert_block` / `cli` 的 `expand`
  步骤与 `compress` 合并块都调它）。别在命令层再手写块字典：以前四处各抄一遍，实库里 9 份 plan 的
  158 个块没有 `exec` 就是这么来的。只有 `compress` 写的 `folded_from` 归 `BLOCK_HISTORY_FIELDS`，
  **不进那张表**（不是每个块都有）。
- **老数据的缺键是「读时补齐、写时落盘」**：`store.load()` 调 `model.normalize_block()`（只补不改、不删），
  只读命令跑完文件一个字节不变；**写操作**才把这些键材料化进 `plan.json`。所以对拉改动前后时，
  老 plan 的文件里可能多出 `exec: {}`（语义 no-op）—— 别当成行为差异，要报就先说清是读出来的还是写出来的。
- **只动模型/内部实现时，`--help` 的子命令表两份一模一样**：对拉「跑的是哪一份代码」不能拿它当判据，
  要印这次真动过的记号（例：`python3 -c "from loomerto import model; print('BLOCK_FIELDS' in dir(model))"`）。
- **给用户的结论要先给现象与命令**：他问「支持吗 / 入口在哪」时，先给「存在 / 不存在 + 入口命令」+
  一条真跑过的输出，再讲机制与落点；他会直接拿着命令去试。
- **别把「只读的核查」变成待决项问他**：能自己跑掉的就跑掉（现状清单、回归、diff），
  留给他的只有「动哪份数据 / 定哪个口径」。

## Support files

| 文件 | 承担什么 |
|---|---|
| `references/loomerto-cli-location-and-cli-conventions.md` | 定位解析顺序表、文件模式位置参数左移的实现要点（含 `optional` 格子）、改旗标时的验收矩阵与跑矩阵的现成形状（§3.1：取旧版 / 断言器 / 子命令自检）、改完拉平副本的命令 |
| `references/object-definition-and-operation-map.md` | plan / task / block 各自的定义在哪、操作落哪一层、按对象切不动的地方、与硬规则 4 的关系（回答「每个对象如何定义」「按对象分 module」时先看它） |
