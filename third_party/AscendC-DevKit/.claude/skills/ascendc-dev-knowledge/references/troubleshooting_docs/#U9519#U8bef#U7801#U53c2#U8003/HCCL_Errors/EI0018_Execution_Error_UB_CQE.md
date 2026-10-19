# EI0018 Execution_Error_UB_CQE

**页面ID:** atlaserrorcode_15_0382  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/troubleshooting/atlaserrorcode_15_0382.html

---

#### Symptom

An error CQE occurred during operator execution. Local information: server %s, device ID %s, device IP %s. Peer information: server %s, device ID %s, device IP %s.

#### Possible Cause

1. The network between two devices is abnormal. For example, the network port is intermittently disconnected.

2. The peer process exits unexpectedly in advance. As a result, the local end cannot receive the response from the peer end.

3.The hardware of the HBM or UB chip processing module of either device is abnormal.

#### Solution

1. Check whether the network devices between the two ends are abnormal. Generally, packet loss occurs due to intermittent disconnection of the port. If the ping test fails, check whether the port is linkdown or the network configuration is incorrect.

2. Check whether the peer process exits first. If yes, check the reason why the process exit.

3.Use the RAS fault check mechanism to check whether the hardware of the HBM or UB chip processing module of either device is abnormal.If the hardware is abnormal, contact Huawei technical support.
