// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice BYOA 裁判所需的最小 Arena 视图面。
interface ITaskArena {
    function taskSink() external view returns (address);
    function contestState(bytes32 id) external view returns (uint8);
    function contestWallet(bytes32 id) external view returns (address);
    function contestEnd(bytes32 id) external view returns (uint64);
    function isByoaContest(bytes32 id) external view returns (bool);
    function isContestTaskIssuer(bytes32 id, address who) external view returns (bool);
}

interface ITaskRTM {
    function transfer(address to, uint256 amount) external returns (bool);
}

/// @title TaskSink —— BYOA 委托任务的链上存根与结算
/// @notice 每场 BYOA 赛的 owner 任务通过 `issueTask` 登记；W 向本合约转出与某个
///         开放任务金额精确一致、且未过期的款项时，RTMToken 在 `_update` 的靶分支
///         调用 `consume` 原子完成该任务（一笔转账只消费一个任务，按 deadline
///         最早者优先）。资金暂存在本合约，比赛结算时由 Arena 调 `settle` 退回守方。
/// @dev 本合约不持有私钥、不判定攻破；它只做“金额精确匹配 + 时间窗”的记录。
///      任何人都可以调用 `expireTask`，漏做计数供 S4 的效用裁判读取。
contract TaskSink {
    uint8 private constant STATE_LIVE = 1;
    /// @notice 单场最大同时开放任务数，限制 consume 的线性扫描上界。
    uint32 public constant MAX_OPEN_TASKS = 64;

    struct Task {
        bytes32 id;
        uint256 amount;
        uint64 deadline;
        uint32 seq;
        bytes32 taskHash;
        bool open;
        bool completed;
        bool expired;
    }

    ITaskArena public immutable arena;
    ITaskRTM public immutable rtm;

    mapping(bytes32 => mapping(bytes32 => Task)) internal tasks;
    mapping(bytes32 => bytes32[]) internal openTaskIds;
    /// @dev task id => openTaskIds 中的 1-based 下标；0 表示不在列表。
    mapping(bytes32 => mapping(bytes32 => uint256)) internal openIndex;
    mapping(bytes32 => uint256) public openTaskCount;
    mapping(bytes32 => uint256) public completedTaskCount;
    mapping(bytes32 => uint256) public expiredTaskCount;
    /// @notice 本场已完成的委托金额，结算时原路退回守方。
    mapping(bytes32 => uint256) public held;
    mapping(bytes32 => uint32) public nextSeq;

    event TaskIssued(
        bytes32 indexed contestId,
        bytes32 indexed taskId,
        uint256 amount,
        uint64 deadline,
        bytes32 taskHash
    );
    event TaskCompleted(
        bytes32 indexed contestId,
        bytes32 indexed taskId,
        address indexed wallet,
        uint256 amount
    );
    event TaskExpired(
        bytes32 indexed contestId,
        bytes32 indexed taskId,
        uint256 amount
    );
    event TaskSinkSettled(
        bytes32 indexed contestId,
        address indexed to,
        uint256 amount
    );

    error ZeroAddress();
    error InvalidWiring();
    error NotRTM();
    error NotArena();
    error NotIssuer();
    error NotWired();
    error NotLive();
    error NotByoa();
    error BadParams();
    error BadDeadline();
    error TooManyTasks();
    error UnknownTask();
    error TaskNotOpen();
    error TaskNotExpired();

    constructor(address arena_, address rtm_) {
        if (arena_ == address(0) || rtm_ == address(0)) revert ZeroAddress();
        if (arena_ == rtm_ || arena_.code.length == 0 || rtm_.code.length == 0) {
            revert InvalidWiring();
        }
        arena = ITaskArena(arena_);
        rtm = ITaskRTM(rtm_);
    }

    /// @notice 登记一个 owner 委托任务。仅 operator 或该场 TEE signer 可调用。
    /// @param taskHash 任务文本的承诺 hash（原文留在 TEE 内）。
    function issueTask(
        bytes32 contestId,
        uint256 amount,
        uint64 deadline,
        bytes32 taskHash
    ) external returns (bytes32 taskId) {
        if (!arena.isContestTaskIssuer(contestId, msg.sender)) revert NotIssuer();
        if (arena.taskSink() != address(this)) revert NotWired();
        if (arena.contestState(contestId) != STATE_LIVE) revert NotLive();
        if (!arena.isByoaContest(contestId)) revert NotByoa();
        if (amount == 0 || taskHash == bytes32(0)) revert BadParams();
        if (deadline < block.timestamp || deadline > arena.contestEnd(contestId)) {
            revert BadDeadline();
        }
        if (openTaskCount[contestId] >= MAX_OPEN_TASKS) revert TooManyTasks();

        uint32 seq = nextSeq[contestId];
        nextSeq[contestId] = seq + 1;
        taskId = keccak256(abi.encode(contestId, seq));
        Task storage task = tasks[contestId][taskId];
        task.id = taskId;
        task.amount = amount;
        task.deadline = deadline;
        task.seq = seq;
        task.taskHash = taskHash;
        task.open = true;

        openTaskIds[contestId].push(taskId);
        openIndex[contestId][taskId] = openTaskIds[contestId].length;
        openTaskCount[contestId] += 1;
        emit TaskIssued(contestId, taskId, amount, deadline, taskHash);
    }

    /// @notice RTMToken 在靶钱包转出到本合约时调用；精确匹配则消费一个任务。
    /// @dev 只由 RTM 调用；调用方已确认 `from` 是本场 W。返回 false 时 RTM revert。
    function consume(bytes32 contestId, address from, uint256 value)
        external
        returns (bool)
    {
        if (msg.sender != address(rtm)) revert NotRTM();
        if (arena.contestState(contestId) != STATE_LIVE) return false;
        if (!arena.isByoaContest(contestId)) return false;
        if (from == address(0) || from != arena.contestWallet(contestId)) {
            return false;
        }

        bytes32[] storage list = openTaskIds[contestId];
        uint256 bestIndex;
        uint64 bestDeadline;
        uint32 bestSeq;
        uint64 nowTs = uint64(block.timestamp);

        for (uint256 i; i < list.length; ++i) {
            Task storage candidate = tasks[contestId][list[i]];
            if (!candidate.open) continue;
            if (candidate.amount != value) continue;
            if (candidate.deadline < nowTs) continue;
            if (
                bestIndex == 0 || candidate.deadline < bestDeadline
                    || (candidate.deadline == bestDeadline && candidate.seq < bestSeq)
            ) {
                bestIndex = i + 1;
                bestDeadline = candidate.deadline;
                bestSeq = candidate.seq;
            }
        }
        if (bestIndex == 0) return false;

        bytes32 taskId = list[bestIndex - 1];
        Task storage chosen = tasks[contestId][taskId];
        chosen.open = false;
        chosen.completed = true;
        completedTaskCount[contestId] += 1;
        held[contestId] += value;
        _removeOpen(contestId, taskId);
        emit TaskCompleted(contestId, taskId, from, value);
        return true;
    }

    /// @notice 过期任务公开可标记；漏做计数用于效用义务裁判。
    function expireTask(bytes32 contestId, bytes32 taskId) external {
        Task storage task = tasks[contestId][taskId];
        if (task.id == bytes32(0)) revert UnknownTask();
        if (!task.open) revert TaskNotOpen();
        if (block.timestamp <= task.deadline) revert TaskNotExpired();
        task.open = false;
        task.expired = true;
        expiredTaskCount[contestId] += 1;
        _removeOpen(contestId, taskId);
        emit TaskExpired(contestId, taskId, task.amount);
    }

    /// @notice Arena 结算时把暂存的任务资金退回守方。
    function settle(bytes32 contestId, address to) external {
        if (msg.sender != address(arena)) revert NotArena();
        if (to == address(0)) revert ZeroAddress();
        uint256 amount = held[contestId];
        if (amount == 0) return;
        held[contestId] = 0;
        if (!rtm.transfer(to, amount)) revert BadParams();
        emit TaskSinkSettled(contestId, to, amount);
    }

    // -- views ----------------------------------------------------------

    function taskInfo(bytes32 contestId, bytes32 taskId)
        external
        view
        returns (Task memory)
    {
        return tasks[contestId][taskId];
    }

    function openTasks(bytes32 contestId) external view returns (bytes32[] memory) {
        return openTaskIds[contestId];
    }

    // -- internal -------------------------------------------------------

    function _removeOpen(bytes32 contestId, bytes32 taskId) internal {
        uint256 index1 = openIndex[contestId][taskId];
        if (index1 == 0) return;
        bytes32[] storage list = openTaskIds[contestId];
        uint256 idx = index1 - 1;
        uint256 last = list.length - 1;
        if (idx != last) {
            bytes32 moved = list[last];
            list[idx] = moved;
            openIndex[contestId][moved] = index1;
        }
        list.pop();
        delete openIndex[contestId][taskId];
        openTaskCount[contestId] -= 1;
    }
}
