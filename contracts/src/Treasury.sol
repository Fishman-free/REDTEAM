// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title Treasury —— 平台收入归集
/// @notice 消息手续费、数据销售平台分成、挖矿攻破补铸的归集地址。
/// @dev 挖矿层没有罚款；每场挖矿赛创建前由 owner 预打款恰好 1 RTM 到新 W，
///      攻破时 Arena 补铸 1 RTM 回本合约、未攻破退役时 W 余额退回本合约。
///      平台资金唯一出口是 owner 提现；退款场景由 owner 精确授权 Arena
///      从本合约划转（refundUnserved）。
contract Treasury is Ownable {
    using SafeERC20 for IERC20;

    event Withdrawn(address indexed token, address indexed to, uint256 amount);
    event SpenderApproved(address indexed token, address indexed spender, uint256 amount);

    constructor(address initialOwner) Ownable(initialOwner) {}

    /// @notice owner 提取 Treasury 持有的任意 ERC-20。
    function withdraw(IERC20 token, address to, uint256 amount) external onlyOwner {
        token.safeTransfer(to, amount);
        emit Withdrawn(address(token), to, amount);
    }

    /// @notice owner 授权 spender（通常为 Arena）从 Treasury 划转指定额度。
    /// @dev forceApprove 兼容非标准（需先清零）的 ERC-20。
    function approveSpender(IERC20 token, address spender, uint256 amount) external onlyOwner {
        token.forceApprove(spender, amount);
        emit SpenderApproved(address(token), spender, amount);
    }
}
