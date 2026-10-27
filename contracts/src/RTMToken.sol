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
/// @notice "REDTEAM" (RTM)。发币由 Arena 红队挖矿线性注入（无减半、无总量上限）。
/// @dev "标记"语义：活跃靶钱包（守方智能体的钱包 W）的转出只有两个合法去向——
///      该场注册攻方（触发 Arena.onBreach 原子结算）或 Arena 的
///      `controllerTransfer` 控制器划转。其余任何转出（含守方小号、任意第三方，
///      以及 Arena 地址本身）一律 revert TargetTransferRestricted。
///      转入靶钱包不受限；靶注销后恢复普通钱包。
contract RTMToken is ERC20, Ownable {
    /// @notice 唯一铸币者/控制器（Arena），部署时绑定，不可更换。
    address public immutable minter;

    /// @notice 靶钱包 => 所在比赛 id（bytes32(0) 表示非靶）。
    mapping(address => bytes32) public targetContest;

    /// @notice Arena 合约（即 minter，单独存储便于类型化调用）。
    IRTMArena public immutable arena;

    event TargetRegistered(address indexed wallet, bytes32 indexed contestId);
    event TargetUnregistered(address indexed wallet, bytes32 indexed contestId);
    event Breach(bytes32 indexed contestId, address indexed winner, uint256 amount);
    event MiningMinted(address indexed to, uint256 amount);

    error NotMinter();
    error ZeroAddress();
    error InvalidMinter();
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

    /// @notice 注册靶钱包：仅 Arena。
    function registerTarget(address wallet, bytes32 contestId) external {
        if (msg.sender != minter) revert NotArena();
        if (wallet == address(0)) revert ZeroAddress();
        targetContest[wallet] = contestId;
        emit TargetRegistered(wallet, contestId);
    }

    /// @notice 注销靶钱包：仅 Arena。注销后钱包恢复普通 ERC-20 行为。
    function unregisterTarget(address wallet) external {
        if (msg.sender != minter) revert NotArena();
        bytes32 id = targetContest[wallet];
        delete targetContest[wallet];
        emit TargetUnregistered(wallet, id);
    }

    /// @notice 是否活跃靶。
    function isTarget(address wallet) external view returns (bool) {
        return targetContest[wallet] != bytes32(0);
    }

    /// @notice 挖矿铸币：仅 Arena。无年份预算，无总量上限。
    function mint(address to, uint256 amount) external {
        if (msg.sender != minter) revert NotMinter();
        if (to == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        _mint(to, amount);
        emit MiningMinted(to, amount);
    }

    /// @notice 结算/退款/赎回的唯一划转入口（仅 Arena）。
    /// @dev 绕过靶策略；若 from 仍是活跃靶，先注销再划转（CEI）。
    ///      Arena 不得用 transferFrom + allowance 移动 W 资金。
    function controllerTransfer(address from, address to, uint256 amount) external {
        if (msg.sender != minter) revert NotArena();
        if (to == address(0)) revert ZeroAddress();
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
