# 修复说明 — 批跑收尾编译失败(CMakeLists.txt 被快照漏存、被回滚删除)

- **日期**:2026-10-12
- **提交**:`c12277c2`(fix(precision-debug): 入口快照排除表豁免 CMakeLists.txt)
- **关联**:评估报告 P13(`post-merge-assessment.md` §6)· 四层文档(`docs/plan/precision-debug-cmakelists-snapshot/`)· 台账 M5 后续追记
- **定位**:面向阅读的说明文档——这次到底是什么问题、为什么会发生、改了什么。决策与实施细节的产权在四层文档,本文只引用。

---

## 1. 一句话结论

编译失败**不是因为 kernel 代码有问题**——kernel 早就修好并且跑绿了。失败是一个"版本管理"问题:算子编译必需的构建清单文件 `CMakeLists.txt` **存档时被漏掉、回滚时被当垃圾删掉**。之后每次重新编译,cmake 第一步就找不到它,3 秒即死。

## 2. 先补三个背景知识(不懂为什么会出问题,基本都是缺这三块)

### 2.1 git 里的文件分两种

| | 已跟踪(提交进过版本库) | 未跟踪(从没提交过) |
|---|---|---|
| `git checkout 某版本` | 会还原 | 不碰 |
| `git clean` | 不碰 | **当垃圾直接删除** |

本次的 `CMakeLists.txt` 属于**未跟踪**——它是给新算子生成的新文件,从头到尾没人把它提交进 git。

### 2.2 每个算子目录必须有自己的 CMakeLists.txt

cann-bench 工程的构建方式:顶层 `csrc/ops/CMakeLists.txt` 自动扫描每个算子子目录,**要求**子目录里有自己的 `CMakeLists.txt`(声明"我这个算子由哪些源文件组成、怎么注册进编译")。仓库原生的 add、sqrt 算子,这个文件在 git 里;新生成的 `mse_loss_cross_entropy_loss`,这份文件只在磁盘上,git 不知道它存在。

**没有它,整个工程编译不了**——顶层扫描到这个算子目录时直接报 `does not contain a CMakeLists.txt file`。

### 2.3 这套工作流有"存档"和"读档"两个动作

- **存档(入口快照)**:precision_debug 开始时,把工作区里生成的代码文件用一次 `git commit` 固定下来——相当于**拍照存档**,以后随时能回到这个状态。
- **读档(收尾回滚)**:跑批结束时,框架想在"最优代码提交"上**重新编译一遍做最终验证**,做法是 `git checkout`(把文件恢复到那个提交)+ `git clean`(把照片里没有的文件全删掉,保证工作区干净)。

## 3. 事故是怎么一步步发生的

```
① 算子生成   CMakeLists.txt 出现在磁盘上(未跟踪)
              → 此时一切正常:编译只看磁盘,不看 git

② 入口快照   拍照存档,但快照有张"黑名单":
              调试日志/备份/调试文本(.txt)不许进照片
              → CMakeLists.txt 因为以 .txt 结尾被误杀,照片里没有它
              (profile 配置明明写了"要提交 CMakeLists.txt",
               但黑名单是框架级硬规则,压过了配置的声明)

③ 诊断修 kernel  诊断 agent 修好 kernel、提交 3 个修复 commit,
              并在 12:32 把修好的包编译+安装好
              → 此刻一切正常:CMakeLists.txt 还在磁盘上(没被谁动过)

④ 收尾回滚   框架要"回到最优提交 dfa6242 重新编译验证":
              git checkout 恢复照片里的文件
              + git clean 把照片外的文件全删
              → CMakeLists.txt 从磁盘上消失 ⚠️

⑤ 重新编译   converge 重部署、cannbench_adapt 的 clean rebuild,
              两次都在 cmake 第一步死于:
              "The source directory .../mse_loss_cross_entropy_loss
               does not contain a CMakeLists.txt file"
              → 3 秒即死 → 标 deploy_failed
              —— 这就是报告里唯一的红色 error 阶段
```

**黑名单为什么会误杀?** 它的本意是"调试时产生的文本垃圾(`notes.txt`、`case1.txt` 这类抓拍输出)不要进版本库"。用**后缀**当判断依据是偷懒的做法——大多数 `.txt` 确实是垃圾,但 `CMakeLists.txt` 是正经的构建基础设施,名字撞上了。

**为什么叫"回滚后重建必死"?** 因为 ② 和 ④ 是连环的:照片里没存这个文件(②),读档时它就会被删(④),删了之后谁都编译不了(⑤)。**只要快照是完整的,`git clean` 就无害**——checkout 能把一切恢复回来。所以根在快照,不在回滚。

## 4. 那评测的 100% 成绩还可信吗?——可信

收尾编译失败后,评测(cannbench_eval)用的是**之前已经编译好的包**。查证结果:

- 这个包是 **12:32:47** 安装的——诊断 agent **修好 kernel 之后**自己重新编译安装的那一版;
- run_tests 的 129/129 全绿,测的就是这一份;
- 所以 eval 的 100% **测的就是修好的 kernel,成绩没有失真**。

丢的不是成绩,是一个形式保证:"最终最优提交,从头独立编译一遍也能过"这件事没有被验证过——因为编译这步根本走不通。修复后我们把这一步补上了(见下)。

## 5. 改了什么

| 改动 | 内容 |
|---|---|
| **根修**(`git_safety.py`,1 处条件) | 快照黑名单对 `CMakeLists.txt` 这个**精确文件名**放行;其余 `.txt`(调试文本)照旧拦截。以后任何批次的算子,生成的 CMakeLists.txt 都会进快照,回滚永远能恢复 |
| **现场修复**(cann-bench worktree) | 照同仓 add/sqrt 模板,把丢失的 `mse_loss_cross_entropy_loss/CMakeLists.txt` 手工补回来 |
| **不改 `git clean`** | 文件会丢是因为快照没存它,不是 clean 的错;快照修好后 clean 才是安全的。在回滚端打补丁属症状修复 |

## 6. 怎么验证的

| 项 | 结果 |
|---|---|
| TDD 红测试 | 先写用例(profile 声明要提交 CMakeLists.txt + 调试文本并存),改前失败——且失败方式**就是事故本身**:提交为空、"op_dir 仍脏" |
| TDD 绿 | 修复后通过:CMakeLists.txt 进快照提交,调试 `stderr_case.txt` 仍被拦在提交外(黑名单本职不破坏) |
| 回归 | orchestration 全目录 **2239 passed / 0 failed** |
| 现场重建 | 在最优提交 dfa6242 上重新 `build.sh` → **成功**(就是 12:36 失败的那一步) |
| 端到端 smoke | 重建的包装到旁路目录(不动原 run 产物),NPU 上真实调用算子,产出有限结果 → **SMOKE PASSED** |

## 7. 遗留说明(两条,如实)

1. **worktree 里补回的 CMakeLists.txt 保持未跟踪**——那是每个批次用完即弃的瞬态仓,提交会改动已完结 run 的提交史。根治靠快照修复,下个批次的入口快照会自动把它存进版本库。
2. **本次 run 的 `converge_mismatch` 标记保留不抹**——它是如实的历史记录;它所指向的"最终提交态没被复验"这个缺口,已由第 6 节的现场重建+smoke 物理补齐。
