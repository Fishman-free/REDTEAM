// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title Faucet —— 测试网水龙头
/// @notice 后端签发 EIP-712 票据（captcha/OAuth 防女巫），用户凭票领取固定额度 tRTM。
/// @dev 票据与调用者绑定：只有 ticket.to 本人可 claim，防止转卖/代领。
///      nonce 每地址严格递增（0 视为未用，故首张票据 nonce 必须 > 0），
///      deadline 当秒仍有效；同一地址两次领取至少间隔 24h。
///      Faucet 的 tRTM 由 Arena.mintForTest 预充（仅 testnet 部署可用）。
contract Faucet is Ownable, EIP712 {
    using SafeERC20 for IERC20;

    struct Ticket {
        address to;
        uint256 nonce;
        uint64 deadline;
    }

    bytes32 public constant TICKET_TYPEHASH =
        keccak256("Ticket(address to,uint256 nonce,uint64 deadline)");

    /// @notice 发放的代币、票据签名者与单次额度在部署时固定。
    IERC20 public immutable rtm;
    address public immutable ticketSigner;
    uint256 public immutable dripAmount;
    /// @notice 同一地址两次领取的最短间隔。
    uint64 public constant COOLDOWN = 24 hours;

    /// @notice 已用最大 nonce；新票据必须严格大于该值。
    mapping(address => uint256) public nonces;
    /// @notice 上次领取的区块时间戳；0 表示从未领取。
    mapping(address => uint256) public lastClaim;

    event Claimed(address indexed to, uint256 nonce, uint256 amount);

    error InvalidSigner();
    error NonceUsed();
    error Expired();
    error Cooldown(uint256 remaining);
    error NotTicketHolder();
    error ZeroAddress();
    error BadParams();

    constructor(address initialOwner, IERC20 rtm_, address ticketSigner_, uint256 dripAmount_)
        Ownable(initialOwner)
        EIP712("RTM Faucet", "1")
    {
        if (address(rtm_) == address(0)) revert ZeroAddress();
        if (ticketSigner_ == address(0)) revert ZeroAddress();
        if (dripAmount_ == 0) revert BadParams();
        rtm = rtm_;
        ticketSigner = ticketSigner_;
        dripAmount = dripAmount_;
    }

    /// @notice 凭后端签发的 EIP-712 票据领取固定额度。
    /// @dev 校验顺序固定：持有人 -> 过期 -> nonce -> 签名 -> 冷却；
    ///      记账先于转账（CEI）。
    function claim(Ticket calldata ticket, bytes calldata sig) external {
        if (msg.sender != ticket.to) revert NotTicketHolder();
        if (block.timestamp > ticket.deadline) revert Expired();
        if (ticket.nonce <= nonces[ticket.to]) revert NonceUsed();

        bytes32 digest = _hashTypedDataV4(
            keccak256(
                abi.encode(TICKET_TYPEHASH, ticket.to, ticket.nonce, ticket.deadline)
            )
        );
        if (ECDSA.recover(digest, sig) != ticketSigner) revert InvalidSigner();

        uint256 last = lastClaim[ticket.to];
        if (last != 0 && block.timestamp - last < COOLDOWN) {
            revert Cooldown(COOLDOWN - (block.timestamp - last));
        }

        nonces[ticket.to] = ticket.nonce;
        lastClaim[ticket.to] = block.timestamp;
        rtm.safeTransfer(ticket.to, dripAmount);
        emit Claimed(ticket.to, ticket.nonce, dripAmount);
    }
}
