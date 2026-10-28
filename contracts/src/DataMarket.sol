// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @notice Arena 只读接口：价格、身份与比赛状态一律以链上数据为准。
interface IArena {
    struct ContestInfo {
        address defender;
        address wallet;
        uint256 stake;
        uint32 stakeBps;
        bytes32 defenseHash;
        uint64 start;
        uint64 end;
        uint64 endedAt;
        uint8 state;
        bool isMining;
        uint32 attackerCount;
        bool paused;
    }

    function contestInfo(bytes32 id) external view returns (ContestInfo memory);
    function isRegisteredAttacker(bytes32 id, address who) external view returns (bool);
    function dataConsent(bytes32 id, address who) external view returns (bool);
}

/// @title DataMarket —— 比赛数据市场
/// @notice 平台 operator 发布已结束普通比赛的数据根；守方可购买自己的数据或
///         该场注册攻方在加入时已一次性同意出售的进攻数据。成交额 70% 归 Treasury，
///         30% 归数据提供方。挖矿赛数据仅用于 RSI，不发布、不出售。
/// @dev 安全约束：
///      - 买家不能自行传入 stake/身份，S 与 defender 全部从 Arena 读取；
///      - 攻方数据是否可售以 Arena.dataConsent 为唯一事实源：同意在 join 时一次性
///        给出，本合约不保存逐买家授权，也不存在 approveSale 路径；
///      - 每份数据每地址仅可购买一次；先置已购标记再分账（CEI），合约不托管资金。
contract DataMarket is Ownable {
    using SafeERC20 for IERC20;

    /// @notice 平台抽成 70%（按规格保持小写命名）。
    uint256 public constant platformShareBps = 7000;
    /// @notice 守方购买己方数据的价格系数：默认 10% × S。
    uint256 public dataPriceBps = 1000;
    /// @notice 守方购买某位攻方数据的全局固定价（本轮不做按场覆盖）。
    uint256 public attackerDataPrice = 1 ether;

    IERC20 public immutable rtm;
    IArena public immutable arena;
    address public immutable treasury;
    /// @notice 仅有 operator 可发布数据根；owner 可轮换。
    address public operator;

    /// @notice contestId => 数据集 Merkle 根（0 表示未发布）。
    mapping(bytes32 => bytes32) public datasetRoot;
    /// @notice contestId => 守方 => 是否已购买己方数据。
    mapping(bytes32 => mapping(address => bool)) public boughtOwn;
    /// @notice contestId => 攻方 => 买家 => 是否已购买该攻方数据。
    mapping(bytes32 => mapping(address => mapping(address => bool))) public boughtAttacker;

    event DatasetPublished(bytes32 indexed contestId, bytes32 root);
    event DataSold(
        address indexed buyer,
        address indexed seller,
        bytes32 indexed contestId,
        uint256 amount,
        uint256 platformCut
    );
    event OperatorUpdated(address indexed previous, address indexed next);
    event DataPriceUpdated(uint256 bps);
    event AttackerDataPriceUpdated(uint256 price);

    error NotPublished();
    error NotDefender();
    error NotConsented();
    error AlreadyBought();
    error NotOperator();
    error ZeroAddress();
    error ZeroRoot();
    error AlreadyPublished();
    error NotEnded();
    error NotAttacker();
    error NotNormalContest();
    error BadParams();

    modifier onlyOperator() {
        if (msg.sender != operator) revert NotOperator();
        _;
    }

    constructor(address initialOwner, IERC20 rtm_, IArena arena_, address treasury_)
        Ownable(initialOwner)
    {
        if (address(rtm_) == address(0) || address(arena_) == address(0)) revert ZeroAddress();
        if (treasury_ == address(0)) revert ZeroAddress();
        rtm = rtm_;
        arena = arena_;
        treasury = treasury_;
    }

    // ------------------------------------------------------------------
    // 平台配置
    // ------------------------------------------------------------------

    function setOperator(address next) external onlyOwner {
        if (next == address(0)) revert ZeroAddress();
        address previous = operator;
        operator = next;
        emit OperatorUpdated(previous, next);
    }

    function setDataPriceBps(uint256 bps) external onlyOwner {
        if (bps > 10_000) revert BadParams();
        dataPriceBps = bps;
        emit DataPriceUpdated(bps);
    }

    function setAttackerDataPrice(uint256 price) external onlyOwner {
        if (price == 0) revert BadParams();
        attackerDataPrice = price;
        emit AttackerDataPriceUpdated(price);
    }

    // ------------------------------------------------------------------
    // 数据集发布
    // ------------------------------------------------------------------

    /// @notice 仅 operator：发布已结束普通比赛的数据根，一次性。
    /// @dev 挖矿赛数据强制留存但仅用于 RSI，永不发布、不出售。
    function publish(bytes32 contestId, bytes32 root) external onlyOperator {
        if (root == bytes32(0)) revert ZeroRoot();
        // Arena.State.Ended == 2；未结束或未知比赛一律拒绝。
        IArena.ContestInfo memory info = arena.contestInfo(contestId);
        if (info.state != 2) revert NotEnded();
        if (info.isMining) revert NotNormalContest();
        if (datasetRoot[contestId] != bytes32(0)) revert AlreadyPublished();
        datasetRoot[contestId] = root;
        emit DatasetPublished(contestId, root);
    }

    // ------------------------------------------------------------------
    // 购买
    // ------------------------------------------------------------------

    /// @notice 守方购买自己被攻破（或已结束）比赛的数据；自有数据无需攻方同意。
    /// @dev 价格 = S × dataPriceBps / 10000；seller = buyer = defender，
    ///      因此 30% 退回守方自己，净付 70%。不得优化掉这笔转账。
    function buyOwn(bytes32 contestId) external {
        if (datasetRoot[contestId] == bytes32(0)) revert NotPublished();
        IArena.ContestInfo memory info = arena.contestInfo(contestId);
        if (msg.sender != info.defender) revert NotDefender();
        if (info.isMining) revert NotNormalContest();
        if (boughtOwn[contestId][msg.sender]) revert AlreadyBought();

        uint256 amount = (info.stake * dataPriceBps) / 10_000;
        boughtOwn[contestId][msg.sender] = true;
        uint256 platformCut = _split(amount, msg.sender, msg.sender);
        emit DataSold(msg.sender, msg.sender, contestId, amount, platformCut);
    }

    /// @notice 守方购买某位注册攻方的进攻数据；该攻方必须在 join 时已一次性同意。
    /// @dev 同意状态只读 Arena.dataConsent，DataMarket 不保存任何同意副本。
    function buyFromAttacker(bytes32 contestId, address attacker) external {
        if (datasetRoot[contestId] == bytes32(0)) revert NotPublished();
        IArena.ContestInfo memory info = arena.contestInfo(contestId);
        if (msg.sender != info.defender) revert NotDefender();
        if (info.isMining) revert NotNormalContest();
        if (!arena.isRegisteredAttacker(contestId, attacker)) revert NotAttacker();
        if (!arena.dataConsent(contestId, attacker)) revert NotConsented();
        if (boughtAttacker[contestId][attacker][msg.sender]) revert AlreadyBought();

        uint256 amount = attackerDataPrice;
        boughtAttacker[contestId][attacker][msg.sender] = true;
        uint256 platformCut = _split(amount, msg.sender, attacker);
        emit DataSold(msg.sender, attacker, contestId, amount, platformCut);
    }

    /// @dev 从买家直接分账：平台 70% -> Treasury，其余 -> 数据提供方。
    ///      调用方必须先更新已购标记；本合约不持有资金。
    function _split(uint256 amount, address buyer, address seller)
        internal
        returns (uint256 platformCut)
    {
        platformCut = (amount * platformShareBps) / 10_000;
        if (platformCut > 0) {
            rtm.safeTransferFrom(buyer, treasury, platformCut);
        }
        uint256 sellerCut = amount - platformCut;
        if (sellerCut > 0) {
            rtm.safeTransferFrom(buyer, seller, sellerCut);
        }
    }
}
