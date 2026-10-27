// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./RTMToken.sol";

/// @dev 任务 3 的临时占位 Arena：只承担 minter、攻方登记与 onBreach 记录三个职责，
///      无任何访问控制。任务 4 会用真 Arena 替换并删除本文件。
contract ArenaStub {
    mapping(bytes32 => mapping(address => bool)) public attackers;
    bytes32 public lastBreachContest;
    address public lastBreachWinner;
    uint256 public breachCalls;
    bool public revertOnBreach;

    function setAttacker(bytes32 contestId, address who, bool ok) external {
        attackers[contestId][who] = ok;
    }

    function setRevertOnBreach(bool yes) external {
        revertOnBreach = yes;
    }

    function isRegisteredAttacker(bytes32 contestId, address who) external view returns (bool) {
        return attackers[contestId][who];
    }

    function onBreach(bytes32 contestId, address winner) external {
        if (revertOnBreach) revert("ArenaStub: breach reverted");
        lastBreachContest = contestId;
        lastBreachWinner = winner;
        breachCalls += 1;
    }

    function registerTarget(RTMToken rtm, address wallet, bytes32 contestId) external {
        rtm.registerTarget(wallet, contestId);
    }

    function unregisterTarget(RTMToken rtm, address wallet) external {
        rtm.unregisterTarget(wallet);
    }

    function mint(RTMToken rtm, address to, uint256 amount) external {
        rtm.mint(to, amount);
    }

    function controllerSend(RTMToken rtm, address from, address to, uint256 amount) external {
        rtm.controllerTransfer(from, to, amount); // 仅 minter；不需要 allowance
    }
}
