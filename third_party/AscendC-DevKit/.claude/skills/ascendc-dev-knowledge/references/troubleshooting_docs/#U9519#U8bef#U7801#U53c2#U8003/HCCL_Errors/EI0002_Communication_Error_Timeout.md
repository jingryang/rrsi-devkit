# EI0002  Communication_Error_Timeout

**页面ID:** atlaserrorcode_15_0242  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/troubleshooting/atlaserrorcode_15_0242.html

---

#### Symptom

An timeout occurs when the Notify register waits for execution. Waiting peer end: %s; task information: %s; communication operator information: %s; communicator: %s.

#### Possible Cause

1. An exception occurs during the execution on some NPUs in the cluster. As a result, collective communication operation failed.

2. The execution speed on some NPU in the cluster is too slow to complete a communication operation within the timeout interval. (The default timeout interval is 1800s, You can set the interval by using HCCL_EXEC_TIMEOUT.)

3. The number of training samples of each NPU is inconsistent.

4. Packet loss or other connectivity problems occur on the communication link.

#### Solution

1. If this error is reported on part of these ranks, check other ranks to see whether other errors have been reported earlier.

2. If this error is reported for all ranks, check whether the error reporting time is consistent (the maximum difference must not exceed 1800s). If not, locate the cause or set the HCCL_EXEC_TIMEOUT environment variable to a larger value.

3. Ensure that the number of training samples of each NPU is consistent.

4. Check whether the completion queue element (CQE) of the error exists in the plog(grep -rn 'error cqe'). If so, check the network connection status. For details about the troubleshooting method, search for the keyword \"EI0002\" on https://www.hiascend.com/en/document/.
