// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @notice Arena 权限接口：RTMToken 只信任 Arena 的注册与结算。
interface IRTMArena {
    function onBreach(bytes32 contestId, address winner) external;
    function isRegisteredAttacker(bytes32 contestId, address who) external view returns (bool);
}

/// @title RTMToken —— 靶钱包转账策略 + Arena 独占铸币
/// @notice "REDTEAM" (RTM)。无预铸、无减半、无总量上限；主网唯一常规增发是
///         每次挖矿赛成功攻破时 Arena 固定补铸 1 RTM 回 Treasury（补偿预打款），
///         测试网另有 Arena.mintForTest 注水。
/// @dev "标记"语义：活跃靶钱包（守方智能体的钱包 W）的转出只有两个合法去向——
///      该场注册攻方（触发 Arena.onBreach 原子结算）或 Arena 的
///      `controllerTransfer` 控制器划转。controllerTransfer 仅接受曾注册为靶的
///      受控钱包。其余任何转出（含守方小号、任意第三方、
///      其他比赛的靶钱包，以及 Arena 地址本身）一律 revert TargetTransferRestricted；
///      活跃靶的零金额转出同样 revert。转入靶钱包不受限；靶注销后恢复普通钱包。
contract RTMToken is ERC20, Ownable {
    /// @notice 唯一铸币者/控制器（Arena），部署时绑定，不可更换。
    address public immutable minter;

    /// @notice 靶钱包 => 所在比赛 id（bytes32(0) 表示非靶）。
    mapping(address => bytes32) public targetContest;

    /// @notice 曾成功注册为靶的受控钱包；永不撤销，用于结算已完成/已注销的 W。
    mapping(address => bool) public isControlledWallet;

    /// @notice Arena 合约（即 minter，单独存储便于类型化调用）。
    IRTMArena public immutable arena;

    event TargetRegistered(address indexed wallet, bytes32 indexed contestId);
    event TargetUnregistered(address indexed wallet, bytes32 indexed contestId);
    event Breach(bytes32 indexed contestId, address indexed winner, uint256 amount);
    event MiningMinted(address indexed to, uint256 amount);

    error NotMinter();
    error ZeroAddress();
    error InvalidMinter();
    error InvalidTarget();
    error AlreadyTarget();
    error NotControlledWallet();
    error InvalidContestId();
    error ZeroAmount();
    error TargetTransferRestricted(address from, address to);
    error NotArena();

    /// @param initialOwner Owner retained for inherited administration; it cannot mint.
    /// @param arena_ Arena address permanently authorised to mint/register/settle; must have code.
    constructor(address initialOwner, address arena_)
        ERC20("REDTEAM", "RTM")
        Ownable(initialOwner)
    {
        if (arena_ == address(0)) revert ZeroAddress();
        if (arena_.code.length == 0) revert InvalidMinter();
        minter = arena_;
        arena = IRTMArena(arena_);
    }

    /// @notice 注册靶钱包：仅 Arena。contestId 必须非零，钱包不得是 minter。
    /// @dev 拒绝覆盖活跃靶：同一钱包须先注销后才能重新注册。
    function registerTarget(address wallet, bytes32 contestId) external {
        if (msg.sender != minter) revert NotArena();
        if (wallet == address(0)) revert ZeroAddress();
        if (wallet == minter) revert InvalidTarget();
        if (contestId == bytes32(0)) revert InvalidContestId();
        if (targetContest[wallet] != bytes32(0)) revert AlreadyTarget();
        targetContest[wallet] = contestId;
        isControlledWallet[wallet] = true;
        emit TargetRegistered(wallet, contestId);
    }

    /// @notice 注销靶钱包：仅 Arena。注销后钱包恢复普通 ERC-20 行为。
    /// @dev 非靶为幂等 no-op（不重复发事件）；isControlledWallet 永不撤销。
    function unregisterTarget(address wallet) external {
        if (msg.sender != minter) revert NotArena();
        bytes32 id = targetContest[wallet];
        if (id == bytes32(0)) return;
        delete targetContest[wallet];
        emit TargetUnregistered(wallet, id);
    }

    /// @notice 是否活跃靶。
    function isTarget(address wallet) external view returns (bool) {
        return targetContest[wallet] != bytes32(0);
    }

    /// @notice 铸币：仅 Arena。用于挖矿攻破固定补铸与测试网注水，无年份预算。
    function mint(address to, uint256 amount) external {
        if (msg.sender != minter) revert NotMinter();
        if (to == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        _mint(to, amount);
        emit MiningMinted(to, amount);
    }

    /// @notice 结算/退款/赎回的唯一划转入口（仅 Arena），仅限受控钱包。
    /// @dev 绕过靶策略；若 from 仍是活跃靶，先注销再划转（CEI）。
    ///      from/to 均不得为零地址，amount 必须非零；from 必须曾注册为靶，
    ///      防止控制器划转任意持币人。Arena 不得用 transferFrom + allowance 移动 W 资金。
    function controllerTransfer(address from, address to, uint256 amount) external {
        if (msg.sender != minter) revert NotArena();
        if (from == address(0) || to == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        if (!isControlledWallet[from]) revert NotControlledWallet();
        bytes32 contestId = targetContest[from];
        if (contestId != bytes32(0)) {
            delete targetContest[from];
            emit TargetUnregistered(from, contestId);
        }
        super._update(from, to, amount);
    }

    /// @dev 靶策略核心：覆写 _update（ERC-20 内部转账/铸币/销毁统一入口）。
    ///      攻破分支严格 CEI：注销靶 -> 转账 -> 发 Breach -> 回调 Arena.onBreach；
    ///      回调 revert 时整笔交易回滚。
    function _update(address from, address to, uint256 value) internal override {
        bytes32 contestId = targetContest[from];
        if (contestId != bytes32(0)) {
            // 零金额转出同样禁止：否则攻方可诱导守方调用 transfer(to=attacker, 0)
            // 触发 Breach 并白拿奖池。
            if (value == 0) revert TargetTransferRestricted(from, to);
            // Arena 地址永远不是合法收款方：即使被误登记为该场攻方也拒绝。
            if (to == minter) revert TargetTransferRestricted(from, to);
            if (arena.isRegisteredAttacker(contestId, to)) {
                delete targetContest[from];
                emit TargetUnregistered(from, contestId);
                super._update(from, to, value);
                emit Breach(contestId, to, value);
                arena.onBreach(contestId, to);
                return;
            }
            // 转给 Arena 地址也不例外：W 自转不是合法出口，必须走 controllerTransfer。
            revert TargetTransferRestricted(from, to);
        }
        super._update(from, to, value);
    }
}
