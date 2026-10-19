# 简介

**页面ID:** atlasascendc_api_07_00133  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00133.html

---

Mutex用于核内异步流水指令之间的同步处理，其功能类似于传统CPU中的锁机制。通过锁定指定流水再释放流水来完成流水间的同步依赖。每个锁有固定的一个MutexID，该ID可通过用户自定义（范围为0-27）或者通过AllocMutexID/ReleaseMutexID进行申请释放。当用户进行自定义配置时，接口性能达到最优，但此时无法与TQue等接口配合使用，若通过AllocMutexID/ReleaseMutexID申请释放，则可与TQue等框架接口混合使用。

- Lock：根据MutexID获取Mutex，并阻塞当前流水指令队列，直到对应的MutexID被Unlock。
- Unlock：直到前置当前流水指令退出后，根据MutexID释放对应Mutex。

#### 原型定义

```
using MutexID = uint8_t;
class Mutex {
template <pipe_t pipe>
static __aicore__ inline void Lock(MutexID id);
template <pipe_t pipe>
static __aicore__ inline void Unlock(MutexID id);
};
```
