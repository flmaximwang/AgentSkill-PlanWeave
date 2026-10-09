# 只读证据：可直接抄的命令片段

所有远端检查都套在 `perl` 的 alarm 里（macOS 没有 GNU `timeout`，挂住的命令永远不会返回）：

```bash
perl -e 'alarm shift; exec @ARGV' 60 ssh -o BatchMode=yes -o ConnectTimeout=10 <host> 'bash -s' <<'EOF'
# … 只读检查 …
EOF
```

ssh 到 DSM 会先打一行 post-quantum 告警，用 `| grep -v 'WARNING\|vulnerable\|upgraded'` 滤掉，别让它淹没输出。

下面所有片段都在**远端 shell** 里执行（`tail` / `ls` / `du` 是远端工具）；本机侧读文件、找文件仍然用原生
`read_file` / `search_files`。

## 1. 把落盘的长 thread 压成一页

```python
import json
d = json.load(open("<工具结果里给出的落盘路径>"))
msgs = sorted(d["messages"], key=lambda m: int(m["id"]))          # 雪花 id 单调递增 = 时间序
who = lambda m: m["author"].get("display_name") or m["author"]["username"]
for m in msgs:
    print("---", m["timestamp"], "|", who(m), "|", m["id"])
    print(m.get("content", "").replace("\n", " ⏎ ")[:800])
```

先看结构（谁说了几段、哪几条特别长），再决定精读哪几条全文 —— 不要一上来把 100 条全文读进上下文。

## 2. 判活：按 cmdline，不按 `ps`

```bash
for p in /proc/[0-9]*; do
  c=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null)
  case "$c" in *<脚本名>*) echo "ALIVE pid=${p#/proc/}: $c";; esac
done
```

`ps | grep <脚本名>` 在 busybox 上会假阴性（命令被截断成进程名）。

## 3. 双测取速率（同时证明进程活着）

```bash
a=$(ls -1 "$TARGET" | grep -c '<模式>'); echo "T0: $a"
sleep 20
b=$(ls -1 "$TARGET" | grep -c '<模式>'); echo "T20: $b  ⇒ 20 秒变化 $((a-b))"
```

## 4. 抽样换算代替全库统计

```bash
ls -1 "$STORE" | wc -l          # 顶层条目数（一次 readdir，秒级）
du -sh "$STORE"/00              # 单个目录可以；整库 du 在弱 NAS 上就是事故
ls -1 "$STORE"/00 | wc -l       # 抽 10 个顶层目录 → 二级数 + 体积 → 乘顶层数
```

## 5. 时间归属：看 mtime，不做推断

```bash
ls -1 --time-style=+'%m-%d %H:%M' -ld "$DIR"/*/ | head -8   # 抽样，最稳
ls -1 --time-style=+'%m-%d %H:%M' -ld "$DIR"/*/ | awk '{print $6}' | sort | uniq -c   # 条目多就别全量
```

## 6. 分类前先看名字分布，别先套正则

```bash
ls -1 "$DIR" | grep -v '<你的正常模式>' | head -12 | tr '\n' ' '; echo
ls -1 "$DIR" | grep -v '<你的正常模式>' | awk '{print length($0)}' | sort -n | uniq -c
```

「异常」样本若是整齐的另一种长度 / 字符集，多半是你在套错命名规则（git-annex 的 hashdir 是 base62，
会出现 `0G` / `2z` / `Pk`，不是两位十六进制）。

## 7. 落盘数字的写法

在 plan / 状态文档里写成「<时刻> 实测：<数字>（<增量> ⇒ <速率>）」，并注明数据来源（哪条命令、哪个文件）。
任务还在跑时不要写绝对值当结论。
