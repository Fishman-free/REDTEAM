// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {RTMToken, IRTMArena} from "./RTMToken.sol";

/// @notice BYOA 委托任务存根的最小结算接口。
interface ITaskSink {
    function settle(bytes32 contestId, address to) external;
    function expiredTaskCount(bytes32 contestId) external view returns (uint256);
}

/// @title Arena —— 攻守比赛全生命周期
/// @notice 普通赛：质押、惰性罚款（每 2h 保留 75%）、付费消息、攻破/到期/弃权结算，
///         以及测试网注水。挖矿赛：平台固定 1 RTM 奖励、无矿工质押、无罚款、
///         攻破后补铸 1 RTM 并永久退役 defenseHash。
/// @dev 信任模型：守方只 approve 质押，靶钱包 W 由平台在资格测试通过后提交，
///      因此守方无法把任意受害者地址注册为靶。Arena 是 RTMToken 唯一的 minter，
///      W 的资金只能通过 Token 的 controllerTransfer 或“转给本场攻方触发 onBreach”
///      两条路径离开。
///
///      资金分层：
///      - 普通赛 S 由 defender 直达 W（奖池）；
///      - 挖矿赛 W 由 Treasury owner/多签/平台金库服务预打款恰好 1 RTM，create 只校验余额；
///      - 普通攻方质押 s 托管在本合约；矿工无质押；
///      - 消息手续费直达 Treasury；
///      - 罚款仅普通赛，从本合约按需支付给 defender；
///      - 结算只动 W 的余额，且所有 controllerTransfer 均跳过 0 金额；
///      - 挖矿攻破时 Arena 扫尾 W 余额给 winner 后补铸 1 RTM 回 Treasury。
contract Arena is Ownable, ReentrancyGuard, IRTMArena {
    using SafeERC20 for IERC20;

    // ---- 固定参数 ----
    uint64 public constant EPOCH = 2 hours;
    uint256 public constant KEEP_NUM = 75; // 每 epoch 保留 75%
    uint256 public constant KEEP_DEN = 100;
    uint32 public constant MAX_ATTACKERS = 50;
    uint256 public constant FEE_BPS = 50; // 普通赛消息费 = S * 0.5%
    uint256 public constant MINING_REWARD = 1e18; // 每次成功攻破固定 1 RTM
    uint256 public constant MINING_FEE_BPS = 50; // 挖矿消息费 = 1 RTM * 0.5%
    uint64 public constant MIN_DURATION = 6 hours;
    uint64 public constant MAX_DURATION = 7 days;
    uint32 public constant MIN_STAKE_BPS = 200; // 2%
    uint32 public constant MAX_STAKE_BPS = 2000; // 20%
    uint256 public constant PRECISION = 1e18;
    uint32 public constant MAX_ACTIVE_MINING = 3;

    // ---- BYOA / EIP-712 ----
    uint8 public constant ATTESTATION_SIMULATED = 0;
    uint8 public constant ATTESTATION_HARDWARE = 1;
    /// @dev 字段顺序必须与 `_mandateHash` 的 abi.encode 完全一致。
    bytes32 public constant BYOA_MANDATE_TYPEHASH = keccak256(
        "ByoaMandate(address defender,address wallet,address teeSigner,uint256 stake,uint64 duration,uint32 stakeBps,bytes32 configCommitment,bytes32 runtimeMeasurement,bytes32 teePubKey,uint8 attestationTier,bool defenderDataConsent,uint16 utilityMissThreshold,uint16 utilityPenaltyBps,uint64 nonce,uint64 deadline)"
    );
    bytes32 public constant TEE_WALLET_BINDING_TYPEHASH = keccak256(
        "TeeWalletBinding(address defender,address wallet,bytes32 configCommitment,bytes32 runtimeMeasurement,bytes32 teePubKey,uint64 nonce,uint64 deadline)"
    );
    bytes32 private constant EIP712_DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );

    enum State {
        None,
        Live,
        Ended
    }

    struct Contest {
        address defender;
        address wallet;
        uint256 stake;
        uint32 stakeBps;
        bytes32 defenseHash;
        uint64 start;
        uint64 end;
        uint64 endedAt;
        State state;
        bool isMining;
        uint32 attackerCount;
        uint256 pausedTotal;
        uint64 lastPauseAt;
        // ---- BYOA ----
        bool isByoa;
        address teeSigner;
        bytes32 teePubKey;
        bytes32 runtimeMeasurement;
        uint8 attestationTier;
        bool defenderDataConsent;
        uint16 utilityMissThreshold;
        uint16 utilityPenaltyBps;
    }

    /// @notice BYOA 创建参数；configCommitment 复用 defenseHash 槽位。
    struct ByoaParams {
        address defender;
        address wallet;
        address teeSigner;
        uint256 stake;
        uint64 duration;
        uint32 stakeBps;
        bytes32 configCommitment;
        bytes32 runtimeMeasurement;
        bytes32 teePubKey;
        uint8 attestationTier;
        bool defenderDataConsent;
        uint16 utilityMissThreshold;
        uint16 utilityPenaltyBps;
        uint64 nonce;
        uint64 deadline;
    }

    /// @notice BYOA 公开运行时信息（不含私有配置原文）。
    struct ByoaInfo {
        bool isByoa;
        address teeSigner;
        bytes32 teePubKey;
        bytes32 runtimeMeasurement;
        bytes32 configCommitment;
        uint8 attestationTier;
        bool defenderDataConsent;
        uint16 utilityMissThreshold;
        uint16 utilityPenaltyBps;
    }

    struct Attacker {
        uint256 stake;
        uint256 base;
        uint64 joinedAt;
        uint256 pausedAtJoin;
        uint256 attackCount;
        uint256 delivered;
        uint256 penaltyTaken;
        uint256 stakeWithdrawn;
        bool waived;
        bool joined;
        bool dataConsent;
    }

    /// @notice 后端/前端读取的核心比赛参数快照。
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
        bool isByoa;
    }

    RTMToken public rtm;
    address public immutable treasury;
    address public operator;
    bool public immutable testnet;
    uint32 public activeMiningCount;
    /// @notice BYOA 任务存根；旧部署保持为 0。
    address public taskSink;

    /// @notice EIP-712 域分隔符（在构造时固定 chainId 与合约地址）。
    bytes32 public immutable domainSeparator;
    /// @notice 每个守方的下一个 BYOA 创建 nonce（防重放）。
    mapping(address => uint64) public byoaNonce;
    /// @notice 已送达消息的密文回复 hash（BYOA 强制非零）。
    mapping(bytes32 => mapping(address => mapping(bytes32 => bytes32))) public replyHashOf;

    mapping(bytes32 => Contest) internal contests;
    mapping(bytes32 => address[]) public contestAttackers;
    mapping(bytes32 => mapping(address => Attacker)) public attackers;
    mapping(bytes32 => mapping(address => mapping(bytes32 => uint256))) public paidFee;
    /// @notice 消息 hash 一经付费即永久占用；退款只清 paidFee，不清本标记。
    mapping(bytes32 => mapping(address => mapping(bytes32 => bool))) public usedMsg;
    /// @notice 已送达消息标记；已送达不可退款，且每条 hash 只能计一次送达。
    mapping(bytes32 => mapping(address => mapping(bytes32 => bool))) public deliveredMsg;
    /// @notice defenseHash 永久退役标记（攻破或主动退役后均不可复用）。
    mapping(bytes32 => bool) public retiredDefenseHash;
    /// @notice defenseHash => 当前活跃挖矿赛 id（0 表示无活跃赛）。
    mapping(bytes32 => bytes32) public activeDefenseHash;
    bytes32[] public contestList;

    event ContestCreated(
        bytes32 indexed id,
        address indexed defender,
        address wallet,
        uint256 stake,
        uint64 end,
        bool isMining,
        uint32 stakeBps,
        bytes32 defenseHash
    );
    event Joined(
        bytes32 indexed id,
        address indexed attacker,
        uint256 stake,
        bool dataConsent
    );
    event MiningJoined(bytes32 indexed id, address indexed miner, uint256 base);
    event DataConsentRecorded(
        bytes32 indexed id,
        address indexed attacker,
        bool consented,
        bool isMining
    );
    event AttackPaid(
        bytes32 indexed id,
        address indexed attacker,
        bytes32 msgHash,
        uint256 seq,
        uint256 fee
    );
    event MarkDelivered(
        bytes32 indexed id,
        address indexed attacker,
        bytes32 indexed msgHash,
        uint256 delivered,
        bytes32 replyHash
    );
    event ByoaContestCreated(
        bytes32 indexed id,
        address indexed defender,
        address indexed wallet,
        address teeSigner,
        bytes32 configCommitment,
        bytes32 runtimeMeasurement,
        bytes32 teePubKey,
        uint8 attestationTier,
        bool defenderDataConsent
    );
    event TaskSinkUpdated(address indexed sink);
    event ByoaUtilityBreach(
        bytes32 indexed id,
        uint256 expiredTasks,
        uint256 penalty
    );
    event PenaltiesCollected(bytes32 indexed id, address indexed recipient, uint256 amount);
    event Paused(bytes32 indexed id);
    event Unpaused(bytes32 indexed id);
    event DefenderFault(bytes32 indexed id);
    event RefundUnserved(
        bytes32 indexed id,
        address indexed attacker,
        bytes32 msgHash,
        uint256 fee
    );
    event Expired(bytes32 indexed id, address indexed defender, uint256 returned);
    event ContestSettled(bytes32 indexed id, address indexed winner, uint256 amount);
    event StakeWithdrawn(bytes32 indexed id, address indexed attacker, uint256 amount);
    event MiningSettled(
        bytes32 indexed id,
        address indexed winner,
        bytes32 defenseHash,
        uint256 reward
    );
    event MiningRetired(bytes32 indexed id, bytes32 defenseHash, uint256 returned);
    event OperatorUpdated(address indexed operator);

    error ZeroAddress();
    error BadParams();
    error NotInitialized();
    error AlreadyInitialized();
    error InvalidRTM();
    error NotOperator();
    error OnlyToken();
    error NotLive(bytes32 id);
    error ContestUnknown(bytes32 id);
    error NotEnded(bytes32 id);
    error NotExpired(bytes32 id);
    error AlreadyJoined();
    error NotJoined();
    error TooManyAttackers();
    error PausedNow(bytes32 id);
    error NotPaused(bytes32 id);
    error FeeZero();
    error NothingToMark();
    error NothingToRefund();
    error NothingToWithdraw();
    error NotDefender();
    error InvalidWallet(address wallet);
    error BaseZero();
    error StakeTooHigh(uint256 stake, uint256 maxStake);
    error InvalidTreasury();
    error ContestExpired(bytes32 id);
    error TestnetOnly();
    error NotNormalContest();
    error NotMiningContest();
    error DataConsentRequired();
    error HashRetired(bytes32 hash);
    error HashAlreadyActive(bytes32 hash);
    error MiningCapReached();
    error WalletNotFresh(address wallet);
    error WrongPrizeBalance(uint256 balance);
    error ZeroHash();
    error TaskSinkNotSet();
    error TaskSinkAlreadySet();
    error InvalidTaskSink();
    error BadSignature();
    error SignatureExpired();
    error BadNonce();
    error ReplyHashRequired();
    error UtilitySatisfied(uint256 expiredTasks, uint16 threshold);
    error NotByoaContest();

    modifier onlyOperator() {
        if (msg.sender != operator) revert NotOperator();
        _;
    }

    constructor(address initialOwner, address treasury_, bool testnet_) Ownable(initialOwner) {
        if (treasury_ == address(0)) revert ZeroAddress();
        if (treasury_ == address(this) || treasury_.code.length == 0) revert InvalidTreasury();
        treasury = treasury_;
        testnet = testnet_;
        domainSeparator = keccak256(
            abi.encode(
                EIP712_DOMAIN_TYPEHASH,
                keccak256(bytes("RTM Arena")),
                keccak256(bytes("1")),
                block.chainid,
                address(this)
            )
        );
    }

    // ------------------------------------------------------------------
    // 部署/配置
    // ------------------------------------------------------------------

    /// @notice 绑定 RTM。只能调用一次；RTM 必须已有代码且把本合约设为 minter。
    /// @dev 部署顺序：Treasury -> Arena -> RTMToken(arena) -> initialize。
    function initialize(RTMToken rtm_) external onlyOwner {
        if (address(rtm) != address(0)) revert AlreadyInitialized();
        if (address(rtm_) == address(0) || address(rtm_).code.length == 0) revert InvalidRTM();
        if (address(rtm_) == treasury) revert InvalidRTM();
        if (rtm_.minter() != address(this)) revert InvalidRTM();
        if (address(rtm_.arena()) != address(this)) revert InvalidRTM();
        rtm = rtm_;
    }

    function setOperator(address op) external onlyOwner {
        if (op == address(0)) revert ZeroAddress();
        operator = op;
        emit OperatorUpdated(op);
    }

    /// @notice 绑定 BYOA 的 TaskSink 并同步到 RTMToken；只能设置一次。
    /// @dev 必须在 createByoaContest 之前调用；不影响普通赛与挖矿赛。
    function setTaskSink(address sink) external onlyOwner {
        if (address(rtm) == address(0)) revert NotInitialized();
        if (taskSink != address(0)) revert TaskSinkAlreadySet();
        if (sink == address(0) || sink.code.length == 0) revert InvalidTaskSink();
        taskSink = sink;
        rtm.setTaskSink(sink);
        emit TaskSinkUpdated(sink);
    }

    /// @notice 测试网注水：仅 testnet=true 的部署可用。
    /// @dev 主网 testnet=false 时唯一常规增发路径是挖矿攻破补铸 1 RTM。
    function mintForTest(address to, uint256 amount) external onlyOwner nonReentrant {
        if (!testnet) revert TestnetOnly();
        rtm.mint(to, amount);
    }

    // ------------------------------------------------------------------
    // 创建比赛
    // ------------------------------------------------------------------

    /// @notice 平台在资格测试通过后创建普通比赛；守方只 approve，不能指定 W。
    function createContest(
        address defender,
        address wallet,
        uint256 stake,
        uint64 duration,
        uint32 stakeBps
    ) external onlyOperator nonReentrant returns (bytes32 id) {
        if (address(rtm) == address(0)) revert NotInitialized();
        if (defender == address(0)) revert ZeroAddress();
        if (stake == 0) revert BadParams();
        if (duration < MIN_DURATION || duration > MAX_DURATION) revert BadParams();
        if (stakeBps < MIN_STAKE_BPS || stakeBps > MAX_STAKE_BPS) revert BadParams();
        _checkWallet(wallet, defender, true);

        id = _contestId(defender, wallet);
        Contest storage c = contests[id];
        c.defender = defender;
        c.wallet = wallet;
        c.stake = stake;
        c.stakeBps = stakeBps;
        c.start = uint64(block.timestamp);
        c.end = uint64(block.timestamp) + duration;
        c.state = State.Live;
        contestList.push(id);

        // S 直达托管靶钱包 W；守方必须预先 approve 本合约。
        rtm.transferFrom(defender, wallet, stake);
        rtm.registerTarget(wallet, id);
        emit ContestCreated(id, defender, wallet, stake, c.end, false, stakeBps, bytes32(0));
    }

    /// @notice 平台创建挖矿赛：W 已由 Treasury owner 预打款恰好 1 RTM。
    /// @dev 不调用 Treasury.transferFrom、不消耗 allowance；create 只校验余额。
    function createMiningContest(address wallet, bytes32 defenseHash)
        external
        onlyOperator
        nonReentrant
        returns (bytes32 id)
    {
        if (address(rtm) == address(0)) revert NotInitialized();
        if (defenseHash == bytes32(0)) revert ZeroHash();
        if (retiredDefenseHash[defenseHash]) revert HashRetired(defenseHash);
        if (activeDefenseHash[defenseHash] != bytes32(0)) {
            revert HashAlreadyActive(defenseHash);
        }
        if (activeMiningCount >= MAX_ACTIVE_MINING) revert MiningCapReached();
        _checkMiningWallet(wallet);

        id = _contestId(treasury, wallet);
        Contest storage c = contests[id];
        c.defender = treasury;
        c.wallet = wallet;
        c.stake = 0;
        c.stakeBps = 0;
        c.defenseHash = defenseHash;
        c.start = uint64(block.timestamp);
        c.end = type(uint64).max;
        c.state = State.Live;
        c.isMining = true;
        contestList.push(id);
        activeMiningCount += 1;
        activeDefenseHash[defenseHash] = id;

        rtm.registerTarget(wallet, id);
        emit ContestCreated(
            id, treasury, wallet, 0, type(uint64).max, true, 0, defenseHash
        );
    }

    /// @notice 创建 BYOA 赛：守方 EIP-712 委托 + TEE 钱包绑定签名都必须有效。
    /// @param p 运行时公开参数；`configCommitment` 写入 defenseHash 槽位。
    /// @param defenderSignature 守方对 ByoaMandate 的 EIP-712 签名。
    /// @param teeSignature TEE 对 TeeWalletBinding 的 EIP-712 签名。
    function createByoaContest(
        ByoaParams calldata p,
        bytes calldata defenderSignature,
        bytes calldata teeSignature
    ) external onlyOperator nonReentrant returns (bytes32 id) {
        if (address(rtm) == address(0)) revert NotInitialized();
        if (taskSink == address(0)) revert TaskSinkNotSet();
        if (p.defender == address(0) || p.teeSigner == address(0)) {
            revert ZeroAddress();
        }
        if (p.stake == 0) revert BadParams();
        if (p.duration < MIN_DURATION || p.duration > MAX_DURATION) revert BadParams();
        if (p.stakeBps < MIN_STAKE_BPS || p.stakeBps > MAX_STAKE_BPS) revert BadParams();
        if (
            p.configCommitment == bytes32(0) || p.runtimeMeasurement == bytes32(0)
                || p.teePubKey == bytes32(0)
        ) revert BadParams();
        if (p.attestationTier > ATTESTATION_HARDWARE) revert BadParams();
        if (p.utilityMissThreshold > 64) revert BadParams();
        if (p.utilityPenaltyBps > 5000) revert BadParams();
        if (p.deadline < block.timestamp) revert SignatureExpired();
        if (p.nonce != byoaNonce[p.defender]) revert BadNonce();
        _checkWallet(p.wallet, p.defender, true);

        if (_recover(_digest(_mandateHash(p)), defenderSignature) != p.defender) {
            revert BadSignature();
        }
        if (_recover(_digest(_bindingHash(p)), teeSignature) != p.teeSigner) {
            revert BadSignature();
        }

        byoaNonce[p.defender] = p.nonce + 1;

        id = _contestId(p.defender, p.wallet);
        Contest storage c = contests[id];
        c.defender = p.defender;
        c.wallet = p.wallet;
        c.stake = p.stake;
        c.stakeBps = p.stakeBps;
        c.defenseHash = p.configCommitment;
        c.start = uint64(block.timestamp);
        c.end = uint64(block.timestamp) + p.duration;
        c.state = State.Live;
        c.isByoa = true;
        c.teeSigner = p.teeSigner;
        c.teePubKey = p.teePubKey;
        c.runtimeMeasurement = p.runtimeMeasurement;
        c.attestationTier = p.attestationTier;
        c.defenderDataConsent = p.defenderDataConsent;
        c.utilityMissThreshold = p.utilityMissThreshold;
        c.utilityPenaltyBps = p.utilityPenaltyBps;
        contestList.push(id);

        rtm.transferFrom(p.defender, p.wallet, p.stake);
        rtm.registerTarget(p.wallet, id);
        emit ContestCreated(
            id, p.defender, p.wallet, p.stake, c.end, false, p.stakeBps, p.configCommitment
        );
        emit ByoaContestCreated(
            id,
            p.defender,
            p.wallet,
            p.teeSigner,
            p.configCommitment,
            p.runtimeMeasurement,
            p.teePubKey,
            p.attestationTier,
            p.defenderDataConsent
        );
    }

    /// @dev 分块拼装 EIP-712 编码，避免 14 个字段同时占用栈槽。
    ///      abi.encode 的每个标量都按 32 字节右对齐，与 TypedDataEncoder 一致。
    function _mandateHash(ByoaParams calldata p) internal pure returns (bytes32) {
        bytes memory data = abi.encodePacked(
            BYOA_MANDATE_TYPEHASH,
            abi.encode(p.defender, p.wallet, p.teeSigner, p.stake)
        );
        data = abi.encodePacked(
            data, abi.encode(p.duration, p.stakeBps, p.configCommitment)
        );
        data = abi.encodePacked(
            data,
            abi.encode(
                p.runtimeMeasurement,
                p.teePubKey,
                p.attestationTier,
                p.defenderDataConsent,
                p.utilityMissThreshold,
                p.utilityPenaltyBps
            )
        );
        data = abi.encodePacked(data, abi.encode(p.nonce, p.deadline));
        return keccak256(data);
    }

    function _bindingHash(ByoaParams calldata p) internal pure returns (bytes32) {
        bytes memory data = abi.encodePacked(
            TEE_WALLET_BINDING_TYPEHASH,
            abi.encode(p.defender, p.wallet, p.configCommitment)
        );
        data = abi.encodePacked(
            data, abi.encode(p.runtimeMeasurement, p.teePubKey, p.nonce, p.deadline)
        );
        return keccak256(data);
    }

    function _digest(bytes32 structHash) internal view returns (bytes32) {
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator, structHash));
    }

    function _recover(bytes32 digest, bytes calldata signature)
        internal
        pure
        returns (address signer)
    {
        (address recovered, ECDSA.RecoverError error, ) = ECDSA.tryRecover(
            digest, signature
        );
        if (error != ECDSA.RecoverError.NoError) revert BadSignature();
        return recovered;
    }

    function _contestId(address defender, address wallet) internal view returns (bytes32) {
        return keccak256(
            abi.encode(msg.sender, defender, wallet, block.timestamp, contestList.length)
        );
    }

    /// @dev 普通赛靶钱包 W 的准入校验。守方不能指定自己、平台角色、协议合约或已有靶。
    function _checkWallet(address wallet, address defender, bool normal) internal view {
        if (wallet == address(0)) revert ZeroAddress();
        if (
            wallet == address(this) || wallet == address(rtm) || wallet == treasury
                || wallet == operator || wallet == msg.sender
                || (normal && wallet == defender)
        ) revert InvalidWallet(wallet);
        if (rtm.isTarget(wallet)) revert InvalidWallet(wallet);
        // W 单场专用：曾注册为靶（含已结算）的地址永不复用。
        if (rtm.isControlledWallet(wallet)) revert BadParams();
    }

    /// @dev 挖矿赛 W 必须是全新地址：非零、非平台角色、非活跃/历史靶，
    ///      且已由 Treasury 预打款到恰好 MINING_REWARD。
    function _checkMiningWallet(address wallet) internal view {
        if (wallet == address(0)) revert ZeroAddress();
        if (
            wallet == address(this) || wallet == address(rtm) || wallet == treasury
                || wallet == operator || wallet == msg.sender
        ) revert InvalidWallet(wallet);
        if (rtm.isTarget(wallet) || rtm.isControlledWallet(wallet)) {
            revert WalletNotFresh(wallet);
        }
        uint256 balance = rtm.balanceOf(wallet);
        if (balance != MINING_REWARD) revert WrongPrizeBalance(balance);
    }

    // ------------------------------------------------------------------
    // 攻方/矿工动作
    // ------------------------------------------------------------------

    /// @notice 加入普通赛并质押 s = S * stakeBps / 10000；maxStake 为滑点上限。
    /// @param consent join 时一次性选择的数据留存/出售同意，之后不可撤回。
    function join(bytes32 id, uint256 maxStake, bool consent) external nonReentrant {
        Contest storage c = contests[id];
        if (c.state != State.Live) revert NotLive(id);
        if (c.isMining) revert NotNormalContest();
        if (block.timestamp >= c.end) revert ContestExpired(id);
        if (c.lastPauseAt != 0) revert PausedNow(id);
        Attacker storage a = attackers[id][msg.sender];
        if (a.joined) revert AlreadyJoined();
        if (c.attackerCount >= MAX_ATTACKERS) revert TooManyAttackers();

        uint256 base = c.stake;
        if (base == 0) revert BaseZero();
        uint256 s = (base * c.stakeBps) / 10_000;
        if (s == 0) revert BadParams();
        if (s > maxStake) revert StakeTooHigh(s, maxStake);

        a.stake = s;
        a.base = base;
        a.joinedAt = uint64(block.timestamp);
        a.pausedAtJoin = c.pausedTotal;
        a.dataConsent = consent;
        a.joined = true;
        c.attackerCount += 1;
        contestAttackers[id].push(msg.sender);

        rtm.transferFrom(msg.sender, address(this), s);
        emit Joined(id, msg.sender, s, consent);
        emit DataConsentRecorded(id, msg.sender, consent, false);
    }

    /// @notice 加入挖矿赛：无质押、无 approve，数据强制留存。
    /// @param acceptData 必须为 true；矿工数据仅用于 RSI，不进入 DataMarket。
    function joinMining(bytes32 id, bool acceptData) external nonReentrant {
        Contest storage c = contests[id];
        if (c.state != State.Live) revert NotLive(id);
        if (!c.isMining) revert NotMiningContest();
        if (!acceptData) revert DataConsentRequired();
        Attacker storage a = attackers[id][msg.sender];
        if (a.joined) revert AlreadyJoined();
        if (c.attackerCount >= MAX_ATTACKERS) revert TooManyAttackers();

        a.stake = 0;
        a.base = MINING_REWARD;
        a.joinedAt = uint64(block.timestamp);
        a.pausedAtJoin = c.pausedTotal;
        a.dataConsent = true;
        a.joined = true;
        c.attackerCount += 1;
        contestAttackers[id].push(msg.sender);

        emit MiningJoined(id, msg.sender, MINING_REWARD);
        emit DataConsentRecorded(id, msg.sender, true, true);
    }

    /// @notice 为一条待执行消息付费；费用进入 Treasury。
    /// @dev 普通赛 fee = S * 0.5%；挖矿赛 fee = MINING_REWARD * 0.5% = 0.005 RTM。
    function attack(bytes32 id, bytes32 msgHash) external nonReentrant returns (uint256 seq) {
        Contest storage c = contests[id];
        if (c.state != State.Live) revert NotLive(id);
        if (block.timestamp >= c.end) revert ContestExpired(id);
        if (c.lastPauseAt != 0) revert PausedNow(id);
        Attacker storage a = attackers[id][msg.sender];
        if (!a.joined) revert NotJoined();
        if (msgHash == bytes32(0)) revert BadParams();
        if (usedMsg[id][msg.sender][msgHash]) revert BadParams();

        seq = ++a.attackCount;
        uint256 fee = c.isMining
            ? (MINING_REWARD * MINING_FEE_BPS) / 10_000
            : (a.base * FEE_BPS) / 10_000;
        if (fee == 0) revert FeeZero();
        usedMsg[id][msg.sender][msgHash] = true;
        paidFee[id][msg.sender][msgHash] = fee;
        rtm.transferFrom(msg.sender, treasury, fee);
        emit AttackPaid(id, msg.sender, msgHash, seq, fee);
    }

    /// @notice operator 标记一条已付费消息送达；msgHash 必须已付费且只能计一次。
    /// @dev 普通赛/挖矿赛的兼容入口；BYOA 赛必须使用带 replyHash 的重载。
    function markDelivered(bytes32 id, address attacker, bytes32 msgHash)
        external
        onlyOperator
    {
        _markDelivered(id, attacker, msgHash, bytes32(0));
    }

    /// @notice BYOA 送达入口：附带 TEE 加密回复的 hash（必须是密文 keccak）。
    function markDelivered(
        bytes32 id,
        address attacker,
        bytes32 msgHash,
        bytes32 replyHash
    ) external onlyOperator {
        _markDelivered(id, attacker, msgHash, replyHash);
    }

    function _markDelivered(
        bytes32 id,
        address attacker,
        bytes32 msgHash,
        bytes32 replyHash
    ) internal {
        Contest storage c = contests[id];
        if (c.state != State.Live) revert NotLive(id);
        if (block.timestamp >= c.end) revert ContestExpired(id);
        if (c.isByoa && replyHash == bytes32(0)) revert ReplyHashRequired();
        Attacker storage a = attackers[id][attacker];
        if (!a.joined) revert NotJoined();
        if (a.delivered >= a.attackCount) revert NothingToMark();
        if (!usedMsg[id][attacker][msgHash]) revert BadParams();
        // 已退款（paidFee 清零）的消息不可再标记送达。
        if (paidFee[id][attacker][msgHash] == 0) revert BadParams();
        if (deliveredMsg[id][attacker][msgHash]) revert BadParams();
        deliveredMsg[id][attacker][msgHash] = true;
        replyHashOf[id][attacker][msgHash] = replyHash;
        a.delivered += 1;
        emit MarkDelivered(id, attacker, msgHash, a.delivered, replyHash);
    }

    /// @notice operator 退还一条未送达消息的费用（Treasury 需预先授权 Arena）。
    function refundUnserved(bytes32 id, address attacker, bytes32 msgHash)
        external
        onlyOperator
        nonReentrant
    {
        if (deliveredMsg[id][attacker][msgHash]) revert BadParams();
        uint256 fee = paidFee[id][attacker][msgHash];
        if (fee == 0) revert NothingToRefund();
        paidFee[id][attacker][msgHash] = 0;
        IERC20(address(rtm)).safeTransferFrom(treasury, attacker, fee);
        emit RefundUnserved(id, attacker, msgHash, fee);
    }

    // ------------------------------------------------------------------
    // 暂停
    // ------------------------------------------------------------------

    /// @dev 两类比赛均可暂停以停止新消息；普通赛暂停冻结罚款时钟，
    ///      挖矿赛暂停只影响 attack，不影响任何铸币/结算时钟。
    function pause(bytes32 id) external onlyOperator {
        Contest storage c = contests[id];
        if (c.state != State.Live) revert NotLive(id);
        if (block.timestamp >= c.end) revert ContestExpired(id);
        if (c.lastPauseAt != 0) revert PausedNow(id);
        c.lastPauseAt = uint64(block.timestamp);
        emit Paused(id);
    }

    function unpause(bytes32 id) external onlyOperator {
        Contest storage c = contests[id];
        if (c.lastPauseAt == 0) revert NotPaused(id);
        c.pausedTotal += _pauseOverlap(c, c.lastPauseAt, block.timestamp);
        c.lastPauseAt = 0;
        emit Unpaused(id);
    }

    // ------------------------------------------------------------------
    // 惰性罚款（仅普通赛）
    // ------------------------------------------------------------------

    /// @dev 暂停区间 [from, to] 与比赛窗口的交集。跨过 end 的暂停只计到 end，
    ///      避免 endedAt/cutoff 被 end 截断后多扣暂停时长而抹掉已累计罚款。
    function _pauseOverlap(Contest storage c, uint256 from, uint256 to)
        internal
        view
        returns (uint256)
    {
        uint256 capped = to > c.end ? c.end : to;
        return capped > from ? capped - from : 0;
    }

    /// @dev 结束路径统一冻结暂停时钟。at 恒为 block.timestamp。
    function _finalizePause(Contest storage c, uint256 at) internal {
        uint64 lp = c.lastPauseAt;
        if (lp != 0) {
            c.pausedTotal += _pauseOverlap(c, lp, at);
            c.lastPauseAt = 0;
        }
    }

    /// @dev cutoff 取 min(now 或 endedAt, end)；扣除加入后的暂停重叠。
    function _elapsed(Contest storage c, Attacker storage a) internal view returns (uint256) {
        uint256 cutoff = c.state == State.Ended ? c.endedAt : block.timestamp;
        if (cutoff > c.end) cutoff = c.end;
        uint256 eff = cutoff > a.joinedAt ? cutoff - a.joinedAt : 0;

        uint256 paused = c.pausedTotal - a.pausedAtJoin;
        uint64 lp = c.lastPauseAt;
        if (lp != 0) paused += _pauseOverlap(c, lp, cutoff);
        return eff > paused ? eff - paused : 0;
    }

    /// @dev amount * (75/100)^k，1e18 定点平方-乘，O(log k)。
    ///      普通赛 k ≤ D/E ≤ 84，保留 O(log k) 实现。
    function _applyKeep(uint256 amount, uint256 k) internal pure returns (uint256) {
        uint256 base = (KEEP_NUM * PRECISION) / KEEP_DEN;
        uint256 factor = PRECISION;
        while (k > 0) {
            if ((k & 1) == 1) {
                factor = Math.mulDiv(factor, base, PRECISION);
            }
            base = Math.mulDiv(base, base, PRECISION);
            k >>= 1;
        }
        return Math.mulDiv(amount, factor, PRECISION);
    }

    /// @notice 普通攻方当前可退质押（未加入/挖矿赛返回 0）。
    function remainingStake(bytes32 id, address who) public view returns (uint256) {
        Contest storage c = contests[id];
        Attacker storage a = attackers[id][who];
        if (!a.joined) return 0;
        if (c.isMining) return 0;
        uint256 k = _elapsed(c, a) / EPOCH;
        return _applyKeep(a.stake, k);
    }

    /// @notice 累计罚款 = stake - remainingStake。
    function accruedPenalties(bytes32 id, address who) public view returns (uint256) {
        Attacker storage a = attackers[id][who];
        if (!a.joined) return 0;
        return a.stake - remainingStake(id, who);
    }

    /// @notice 尚未拉取的罚款（弃权后为 0）。
    function penaltyDue(bytes32 id, address who) public view returns (uint256) {
        Attacker storage a = attackers[id][who];
        if (a.waived) return 0;
        uint256 accrued = a.stake - remainingStake(id, who);
        return accrued > a.penaltyTaken ? accrued - a.penaltyTaken : 0;
    }

    /// @notice 拉取罚款：仅普通赛、仅 defender；重复调用只拉差额。
    function collectPenalties(bytes32 id) external nonReentrant {
        Contest storage c = contests[id];
        if (c.state == State.None) revert ContestUnknown(id);
        if (c.isMining) revert NotNormalContest();
        if (msg.sender != c.defender) revert NotDefender();

        address[] memory list = contestAttackers[id];
        uint256 total;
        for (uint256 i; i < list.length; ++i) {
            Attacker storage a = attackers[id][list[i]];
            if (a.waived) continue;
            uint256 accrued = a.stake - remainingStake(id, list[i]);
            uint256 due = accrued > a.penaltyTaken ? accrued - a.penaltyTaken : 0;
            if (due > 0) {
                a.penaltyTaken += due;
                total += due;
            }
        }
        if (total == 0) revert NothingToWithdraw();

        rtm.transfer(c.defender, total);
        emit PenaltiesCollected(id, c.defender, total);
    }

    // ------------------------------------------------------------------
    // 结束路径
    // ------------------------------------------------------------------

    /// @dev 所有结束路径统一走这里：冻结暂停、写 endedAt、注销靶。
    ///      挖矿赛额外释放并发名额并永久退役 defenseHash。
    function _end(bytes32 id, Contest storage c, uint256 at) internal {
        _finalizePause(c, at);
        c.state = State.Ended;
        c.endedAt = uint64(at);
        if (c.isMining) {
            // 每个挖矿赛只会 _end 一次；checked 减法防止计数下溢。
            activeMiningCount -= 1;
            bytes32 hash = c.defenseHash;
            retiredDefenseHash[hash] = true;
            activeDefenseHash[hash] = bytes32(0);
        }
        rtm.unregisterTarget(c.wallet);
        // BYOA：暂存在 TaskSink 的合法付款原路退回守方（不进入奖池）。
        if (c.isByoa) {
            address sink = taskSink;
            if (sink != address(0)) ITaskSink(sink).settle(id, c.defender);
        }
    }

    /// @notice 普通赛到期结算：任何人可调；W 余额归 defender，零余额也正常结束。
    function expire(bytes32 id) external nonReentrant {
        Contest storage c = contests[id];
        if (c.isMining) revert NotNormalContest();
        if (c.state != State.Live) revert NotLive(id);
        if (block.timestamp < c.end) revert NotExpired(id);

        _end(id, c, block.timestamp);
        uint256 amount = rtm.balanceOf(c.wallet);
        if (amount > 0) rtm.controllerTransfer(c.wallet, c.defender, amount);
        emit Expired(id, c.defender, amount);
    }

    /// @notice RTMToken 攻破回调：W 被转给登记攻方时触发。
    /// @dev Token 已先注销靶并转出本次 value；本函数把 W 剩余余额也划给 winner。
    ///      普通赛 `block.timestamp >= end` 时整笔回滚，防止到期后诱导转账领取奖池。
    ///      挖矿赛结束后补铸固定 1 RTM 回 Treasury，并发出 MiningSettled。
    function onBreach(bytes32 id, address winner) external override {
        if (msg.sender != address(rtm)) revert OnlyToken();
        Contest storage c = contests[id];
        if (c.state != State.Live) revert NotLive(id);
        if (!c.isMining && block.timestamp >= c.end) revert ContestExpired(id);
        if (!attackers[id][winner].joined) revert NotJoined();

        _end(id, c, block.timestamp);
        uint256 rest = rtm.balanceOf(c.wallet);
        if (rest > 0) rtm.controllerTransfer(c.wallet, winner, rest);

        if (c.isMining) {
            // 补偿平台预打款：净增发固定 1 RTM/成功攻破。
            rtm.mint(treasury, MINING_REWARD);
            emit MiningSettled(id, winner, c.defenseHash, MINING_REWARD);
        } else {
            emit ContestSettled(id, winner, rest);
        }
    }

    /// @notice operator 报告普通赛守方弃权：结束比赛、豁免未拉取罚款、按 delivered 分配 S。
    function reportDefenderFault(bytes32 id) external onlyOperator nonReentrant {
        Contest storage c = contests[id];
        if (c.isMining) revert NotNormalContest();
        if (c.state != State.Live) revert NotLive(id);
        if (block.timestamp >= c.end) revert ContestExpired(id);
        _end(id, c, block.timestamp);

        address[] memory list = contestAttackers[id];
        _waiveAll(id, list);

        uint256 totalDelivered = _totalDelivered(id, list);
        if (totalDelivered == 0) {
            _sweepWallet(c, c.defender);
        } else {
            _distributeByDelivered(c, id, list, totalDelivered);
        }
        emit DefenderFault(id);
    }

    /// @notice 效用义务违约：过期任务数严格超过阈值时，扣罚质押给 Treasury。
    /// @dev 只适用于 BYOA；任务资金先由 `_end` 退回守方，罚没只针对 W 剩余余额。
    ///      攻击方质押不受影响，赛后可正常 withdrawStake。
    function reportByoaUtilityBreach(bytes32 id) external onlyOperator nonReentrant {
        Contest storage c = contests[id];
        if (!c.isByoa) revert NotByoaContest();
        if (c.state != State.Live) revert NotLive(id);
        address sink = taskSink;
        if (sink == address(0)) revert TaskSinkNotSet();
        uint256 expired = ITaskSink(sink).expiredTaskCount(id);
        if (expired <= c.utilityMissThreshold) {
            revert UtilitySatisfied(expired, c.utilityMissThreshold);
        }

        _end(id, c, block.timestamp);
        uint256 balance = rtm.balanceOf(c.wallet);
        uint256 penalty = (c.stake * c.utilityPenaltyBps) / 10_000;
        if (penalty > balance) penalty = balance;
        if (penalty > 0) rtm.controllerTransfer(c.wallet, treasury, penalty);
        balance = rtm.balanceOf(c.wallet);
        if (balance > 0) rtm.controllerTransfer(c.wallet, c.defender, balance);
        emit ByoaUtilityBreach(id, expired, penalty);
    }

    function _waiveAll(bytes32 id, address[] memory list) internal {
        for (uint256 i; i < list.length; ++i) {
            attackers[id][list[i]].waived = true;
        }
    }

    function _totalDelivered(bytes32 id, address[] memory list)
        internal
        view
        returns (uint256 total)
    {
        for (uint256 i; i < list.length; ++i) {
            total += attackers[id][list[i]].delivered;
        }
    }

    function _sweepWallet(Contest storage c, address to) internal {
        uint256 amount = rtm.balanceOf(c.wallet);
        if (amount > 0) rtm.controllerTransfer(c.wallet, to, amount);
    }

    /// @dev 按 delivered 权重分配 S；最后一个非零者取剩余，零 share 跳过，
    ///      W 中超出 S 的部分（或舍入残留）全部退 defender。
    function _distributeByDelivered(
        Contest storage c,
        bytes32 id,
        address[] memory list,
        uint256 totalDelivered
    ) internal {
        uint256 lastIdx;
        for (uint256 i; i < list.length; ++i) {
            if (attackers[id][list[i]].delivered > 0) lastIdx = i;
        }

        uint256 distributed;
        for (uint256 i; i < list.length; ++i) {
            Attacker storage a = attackers[id][list[i]];
            if (a.delivered == 0) continue;
            uint256 share = i == lastIdx
                ? c.stake - distributed
                : (c.stake * a.delivered) / totalDelivered;
            if (share == 0) continue;
            distributed += share;
            rtm.controllerTransfer(c.wallet, list[i], share);
        }
        _sweepWallet(c, c.defender);
    }

    /// @notice 普通赛结束后攻方提走剩余质押；重复调用只提差额。
    /// @dev normal（攻破/到期）：未拉取的罚款留在 Arena 供 defender 事后 collect；
    ///      弃权（waived）：未拉取罚款豁免，攻方提 stake - penaltyTaken。
    function withdrawStake(bytes32 id) external nonReentrant {
        Contest storage c = contests[id];
        if (c.isMining) revert NotNormalContest();
        if (c.state != State.Ended) revert NotEnded(id);
        Attacker storage a = attackers[id][msg.sender];
        if (!a.joined) revert NotJoined();

        uint256 amount;
        if (a.waived) {
            amount = a.stake - a.penaltyTaken - a.stakeWithdrawn;
        } else {
            uint256 remaining = remainingStake(id, msg.sender);
            amount = remaining > a.stakeWithdrawn ? remaining - a.stakeWithdrawn : 0;
        }
        if (amount == 0) revert NothingToWithdraw();

        a.stakeWithdrawn += amount;
        rtm.transfer(msg.sender, amount);
        emit StakeWithdrawn(id, msg.sender, amount);
    }

    // ------------------------------------------------------------------
    // 挖矿退役
    // ------------------------------------------------------------------

    /// @notice 未攻破时由平台主动停止挖矿赛：W 余额退回 Treasury，不铸造。
    /// @dev 仅 Live+isMining；hash 永久 retired；释放并发名额与 active 映射。
    function retireMining(bytes32 id) external onlyOperator nonReentrant {
        Contest storage c = contests[id];
        if (c.state != State.Live) revert NotLive(id);
        if (!c.isMining) revert NotMiningContest();

        _end(id, c, block.timestamp);
        uint256 returned = rtm.balanceOf(c.wallet);
        if (returned > 0) rtm.controllerTransfer(c.wallet, treasury, returned);
        emit MiningRetired(id, c.defenseHash, returned);
    }

    // ------------------------------------------------------------------
    // 视图
    // ------------------------------------------------------------------

    function isRegisteredAttacker(bytes32 id, address who)
        external
        view
        override
        returns (bool)
    {
        return attackers[id][who].joined;
    }

    /// @notice 该场攻方 join 时记录的一次性数据同意；矿工恒为 true。
    /// @dev R3 起 DataMarket 以此校验出售资格；未加入返回 false。
    function dataConsent(bytes32 id, address who) external view returns (bool) {
        return attackers[id][who].dataConsent;
    }

    function contestWallet(bytes32 id) external view returns (address) {
        return contests[id].wallet;
    }

    function contestState(bytes32 id) external view returns (uint8) {
        return uint8(contests[id].state);
    }

    function contestEnd(bytes32 id) external view returns (uint64) {
        return contests[id].end;
    }

    function isByoaContest(bytes32 id) external view returns (bool) {
        return contests[id].isByoa;
    }

    function contestTeeSigner(bytes32 id) external view returns (address) {
        return contests[id].teeSigner;
    }

    /// @notice 任务签发人：operator，或该场 BYOA 的 TEE signer。
    function isContestTaskIssuer(bytes32 id, address who)
        public
        view
        returns (bool)
    {
        Contest storage c = contests[id];
        if (c.state != State.Live) return false;
        if (who == operator) return true;
        return c.isByoa && c.teeSigner != address(0) && who == c.teeSigner;
    }

    /// @notice BYOA 公开运行时信息；非 BYOA 场次 isByoa=false 且字段为零。
    function byoaContestInfo(bytes32 id) external view returns (ByoaInfo memory) {
        Contest storage c = contests[id];
        return ByoaInfo({
            isByoa: c.isByoa,
            teeSigner: c.teeSigner,
            teePubKey: c.teePubKey,
            runtimeMeasurement: c.runtimeMeasurement,
            configCommitment: c.defenseHash,
            attestationTier: c.attestationTier,
            defenderDataConsent: c.defenderDataConsent,
            utilityMissThreshold: c.utilityMissThreshold,
            utilityPenaltyBps: c.utilityPenaltyBps
        });
    }

    /// @notice 返回后端/前端需要的比赛核心参数。
    function contestInfo(bytes32 id) external view returns (ContestInfo memory) {
        Contest storage c = contests[id];
        return ContestInfo({
            defender: c.defender,
            wallet: c.wallet,
            stake: c.stake,
            stakeBps: c.stakeBps,
            defenseHash: c.defenseHash,
            start: c.start,
            end: c.end,
            endedAt: c.endedAt,
            state: uint8(c.state),
            isMining: c.isMining,
            attackerCount: c.attackerCount,
            paused: c.lastPauseAt != 0,
            isByoa: c.isByoa
        });
    }
}
