'use strict';

/**
 * RTM 红队游戏 —— 测试网五合约部署 + wiring + 固定 1 RTM 挖矿烟测 + 地址登记。
 *
 * 运行（在 contracts/ 目录）：
 *   DEPLOY_ALLOW_REDEPLOY=1 \
 *   BESU_TESTNET_RPC=http://127.0.0.1:8546 \
 *   BESU_TESTNET_KEY="$(tr -d '\r\n' < ../infra/besu-testnet/keydir/key)" \
 *   npx hardhat run deploy/deploy-testnet.js --network besu-testnet
 *
 * 环境变量（全部有默认值；地址必须非零，金额必须符合各自约束）：
 *   PLATFORM_ADDRESS          默认 deployer；若不同，注资/烟测后转移五个 Ownable ownership
 *   OPERATOR_ADDRESS          默认 deployer；挖矿烟测要求 operator == deployer
 *   FAUCET_SIGNER_ADDRESS     默认 deployer
 *   FAUCET_DRIP_RTM           默认 200
 *   FAUCET_FUND_RTM           默认 1000000
 *   TREASURY_MINING_FUND      默认 3；必须等于 MINING_REWARD × MAX_ACTIVE_MINING（= 3 RTM）
 *   TREASURY_ALLOWANCE_RTM    默认 0；仅 refundUnserved 权限，不是独立资金
 *   RUN_MINING_SMOKE          默认 1；=0 跳过真实结算烟测
 *   DEPLOY_ALLOW_REDEPLOY=1   允许覆盖已存在的 addresses.json
 *
 * 任何校验失败都会以非零退出码结束；addresses.json 只在全部 assert 通过后写入。
 * 本脚本绝不读取或打印私钥；deployer 私钥只经 Hardhat 的 BESU_TESTNET_KEY 注入。
 * 挖矿烟测的 W 是进程内新生成的随机钱包，私钥不打印、不落盘，用后随进程丢弃。
 *
 * 烟测失败回收：预打款后若 create 已成功且比赛仍 Live，脚本由 operator 调
 * retireMining 把 W 余额退回 Treasury；若 create 未成功（W 尚未成为靶），脚本
 * 用内存中的 W 私钥把余额转回 Treasury。回收失败只告警，不掩盖原始异常，
 * 且失败路径绝不写 addresses.json。
 */

const fs = require('fs');
const path = require('path');
const hre = require('hardhat');

const { ethers } = hre;

const EXPECTED_CHAIN_ID = 48850n;
const EXPECTED_CHAIN_ID_HEX = '0xbed2';
const EXPECTED_NETWORK_NAME = 'besu-testnet';
const ADDRESSES_FILE = path.join(__dirname, 'addresses.json');
const MINING_SMOKE_HASH_INPUT = 'rtm-mining-smoke-v1';

function die(message) {
  throw new Error(message);
}

function normalizeAddress(name, value, fallback) {
  const raw = (value || '').trim() || fallback;
  if (!raw) die(`${name} is required`);
  let address;
  try {
    address = ethers.getAddress(raw);
  } catch {
    die(`${name} must be a valid address (got "${raw}")`);
  }
  if (address === ethers.ZeroAddress) die(`${name} must not be the zero address`);
  return address;
}

function parseAmount(name, value, fallback, { allowZero = false } = {}) {
  const raw = (value || '').trim() || fallback;
  if (!raw) die(`${name} is required`);
  let amount;
  try {
    amount = ethers.parseEther(raw);
  } catch {
    die(`${name} must be a decimal RTM amount (got "${raw}")`);
  }
  if (allowZero ? amount < 0n : amount <= 0n) {
    die(`${name} must be ${allowZero ? 'non-negative' : 'greater than zero'} (got "${raw}")`);
  }
  return amount;
}

function parseToggle(name, value, fallback) {
  const raw = (value || '').trim() || fallback;
  if (raw === '1') return true;
  if (raw === '0') return false;
  die(`${name} must be 0 or 1 (got "${raw}")`);
}

/** 金额展示：整数 RTM 去掉 formatEther 的 ".0" 后缀，保持 addresses.json 可读。 */
function formatRtm(amount) {
  const text = ethers.formatEther(amount);
  return text.endsWith('.0') ? text.slice(0, -2) : text;
}

async function deploy(name, args) {
  const factory = await ethers.getContractFactory(name);
  const contract = await factory.deploy(...args);
  const address = await contract.getAddress();
  await contract.waitForDeployment();
  const receipt = await contract.deploymentTransaction().wait();
  if (!receipt || receipt.status !== 1) die(`${name} deployment failed`);
  console.log(`  deploy ${name.padEnd(11)} ${address}`);
  return contract;
}

async function send(label, txPromise) {
  const tx = await txPromise;
  const receipt = await tx.wait();
  if (!receipt || receipt.status !== 1) die(`${label} reverted`);
  console.log(`  ok     ${label}`);
  return receipt;
}

function assertAddressEq(label, actual, expected) {
  const got = ethers.getAddress(actual);
  const want = ethers.getAddress(expected);
  if (got !== want) die(`assert ${label}: expected ${want}, got ${got}`);
  console.log(`  assert ${label} == ${want}`);
}

function assertEq(label, actual, expected) {
  if (actual !== expected) {
    die(`assert ${label}: expected ${String(expected)}, got ${String(actual)}`);
  }
  console.log(`  assert ${label} == ${String(expected)}`);
}

function findEvent(label, iface, address, receipt, eventName) {
  const wanted = address.toLowerCase();
  for (const log of receipt.logs || []) {
    if (String(log.address).toLowerCase() !== wanted) continue;
    let parsed;
    try {
      parsed = iface.parseLog(log);
    } catch {
      continue;
    }
    if (parsed && parsed.name === eventName) return parsed;
  }
  die(`event ${eventName} for ${label} not found in tx ${receipt.hash}`);
}

/**
 * 真实结算路径烟测（默认执行）：
 *   Treasury owner 预打款 W 1 RTM → operator createMiningContest → joinMining
 *   → W 转 1 RTM 给已加入矿工触发 onBreach → 扫尾/补铸/固定奖励/hash 退役。
 *
 * W 由 ethers.Wallet.createRandom() 在内存生成；私钥绝不打印、绝不写入文件。
 * W 攻破后成为 isControlledWallet 且 hash retired，不可复用；私钥随进程丢弃。
 */
async function runMiningSmoke(ctx) {
  const {
    treasury,
    arena,
    rtm,
    deployerAddress,
    faucetFunding,
    treasuryMiningFund,
    miningReward,
    rpcUrl,
  } = ctx;

  const treasuryAddress = await treasury.getAddress();
  const arenaAddress = await arena.getAddress();
  const rtmAddress = await rtm.getAddress();

  console.log('\nMining smoke test (fixed 1 RTM breach path)...');

  // 独立 RPC provider 只用于让进程内随机钱包签名；节点仍是同一个测试网。
  const rpcProvider = new ethers.JsonRpcProvider(rpcUrl);
  const wallet = ethers.Wallet.createRandom().connect(rpcProvider);
  const w = wallet.address;
  const defenseHash = ethers.id(MINING_SMOKE_HASH_INPUT);
  let contestId = null;
  let prefunded = false;
  console.log(`  smoke W      ${w} (private key in memory only)`);

  try {
    // 独立 provider 也必须指向 48850，防止 BESU_TESTNET_RPC 回退到别的链。
    const smokeNetwork = await rpcProvider.getNetwork();
    if (smokeNetwork.chainId !== EXPECTED_CHAIN_ID) {
      die(
        `smoke provider chainId guard failed: expected ${EXPECTED_CHAIN_ID} ` +
          `(${EXPECTED_CHAIN_ID_HEX}), got ${smokeNetwork.chainId} at ${rpcUrl}`
      );
    }

    assertEq('rtm.balanceOf(W) before pre-fund', await rtm.balanceOf(w), 0n);
    assertEq(
      'rtm.balanceOf(treasury) before pre-fund',
      await rtm.balanceOf(treasuryAddress),
      treasuryMiningFund
    );

    // 先置位再发 tx：即使 wait/网络异常，catch 也按 W 的真实余额决定是否退回收。
    prefunded = true;
    await send(
      `treasury.withdraw(rtm, W, ${formatRtm(miningReward)} RTM)`,
      treasury.withdraw(rtmAddress, w, miningReward)
    );
    assertEq('rtm.balanceOf(W) after pre-fund', await rtm.balanceOf(w), miningReward);
    assertEq(
      'rtm.balanceOf(treasury) after pre-fund',
      await rtm.balanceOf(treasuryAddress),
      treasuryMiningFund - miningReward
    );
    assertEq(
      'rtm.totalSupply() after pre-fund',
      await rtm.totalSupply(),
      faucetFunding + treasuryMiningFund
    );

    const createReceipt = await send(
      'arena.createMiningContest(W, hash)',
      arena.createMiningContest(w, defenseHash)
    );
    const id = await arena.activeDefenseHash(defenseHash);
    if (id === ethers.ZeroHash) {
      die('smoke: activeDefenseHash not set after createMiningContest');
    }
    contestId = id;
    const created = findEvent(
      'arena',
      arena.interface,
      arenaAddress,
      createReceipt,
      'ContestCreated'
    );
    assertEq('ContestCreated.id', created.args.id, id);
    assertEq('ContestCreated.defender', created.args.defender, treasuryAddress);
    assertEq('ContestCreated.wallet', created.args.wallet, w);
    assertEq('ContestCreated.isMining', created.args.isMining, true);
    assertEq('ContestCreated.stakeBps', created.args.stakeBps, 0n);
    assertEq('ContestCreated.defenseHash', created.args.defenseHash, defenseHash);

    assertEq('arena.activeMiningCount() after create', await arena.activeMiningCount(), 1n);
    assertEq('rtm.targetContest(W)', await rtm.targetContest(w), id);
    assertEq('rtm.isTarget(W)', await rtm.isTarget(w), true);
    const info = await arena.contestInfo(id);
    assertEq('contestInfo.state (Live)', info.state, 1n);
    assertEq('contestInfo.isMining', info.isMining, true);
    assertEq('contestInfo.defenseHash', info.defenseHash, defenseHash);
    assertEq('contestInfo.stake', info.stake, 0n);

    const joinReceipt = await send('arena.joinMining(id, true)', arena.joinMining(id, true));
    const joined = findEvent(
      'arena',
      arena.interface,
      arenaAddress,
      joinReceipt,
      'MiningJoined'
    );
    assertEq('MiningJoined.id', joined.args.id, id);
    assertEq('MiningJoined.miner', joined.args.miner, deployerAddress);
    assertEq('MiningJoined.base', joined.args.base, miningReward);

    const roster = await arena.attackers(id, deployerAddress);
    assertEq('attacker.stake', roster.stake, 0n);
    assertEq('attacker.base', roster.base, miningReward);
    assertEq('attacker.dataConsent', roster.dataConsent, true);
    assertEq(
      'arena.dataConsent(id, miner)',
      await arena.dataConsent(id, deployerAddress),
      true
    );

    assertEq('rtm.balanceOf(deployer) before breach', await rtm.balanceOf(deployerAddress), 0n);
    const supplyBeforeBreach = await rtm.totalSupply();

    const breachTx = await rtm
      .connect(wallet)
      .transfer(deployerAddress, miningReward, { gasPrice: 0 });
    const breachReceipt = await breachTx.wait();
    if (!breachReceipt || breachReceipt.status !== 1) die('mining smoke breach tx reverted');
    console.log(`  smoke tx     ${breachReceipt.hash}`);

    const breach = findEvent('rtm', rtm.interface, rtmAddress, breachReceipt, 'Breach');
    assertEq('Breach.contestId', breach.args.contestId, id);
    assertEq('Breach.winner', breach.args.winner, deployerAddress);
    assertEq('Breach.amount', breach.args.amount, miningReward);

    const minted = findEvent(
      'rtm',
      rtm.interface,
      rtmAddress,
      breachReceipt,
      'MiningMinted'
    );
    assertEq('MiningMinted.to', minted.args.to, treasuryAddress);
    assertEq('MiningMinted.amount', minted.args.amount, miningReward);

    const settled = findEvent(
      'arena',
      arena.interface,
      arenaAddress,
      breachReceipt,
      'MiningSettled'
    );
    assertEq('MiningSettled.id', settled.args.id, id);
    assertEq('MiningSettled.winner', settled.args.winner, deployerAddress);
    assertEq('MiningSettled.defenseHash', settled.args.defenseHash, defenseHash);
    assertEq('MiningSettled.reward', settled.args.reward, miningReward);

    assertEq(
      'rtm.balanceOf(deployer) after breach',
      await rtm.balanceOf(deployerAddress),
      miningReward
    );
    assertEq('rtm.balanceOf(W) after breach', await rtm.balanceOf(w), 0n);
    assertEq(
      'rtm.balanceOf(treasury) after breach',
      await rtm.balanceOf(treasuryAddress),
      treasuryMiningFund
    );
    assertEq(
      'rtm.totalSupply() after breach',
      await rtm.totalSupply(),
      supplyBeforeBreach + miningReward
    );
    assertEq('arena.contestState(id) (Ended)', await arena.contestState(id), 2n);
    assertEq('arena.activeMiningCount() after breach', await arena.activeMiningCount(), 0n);
    assertEq('arena.retiredDefenseHash(hash)', await arena.retiredDefenseHash(defenseHash), true);
    assertEq(
      'arena.activeDefenseHash(hash)',
      await arena.activeDefenseHash(defenseHash),
      ethers.ZeroHash
    );
    assertEq('rtm.isTarget(W) after breach', await rtm.isTarget(w), false);
    assertEq('rtm.isControlledWallet(W)', await rtm.isControlledWallet(w), true);
    assertEq('rtm.targetContest(W) after breach', await rtm.targetContest(w), ethers.ZeroHash);

    return {
      txHash: breachReceipt.hash,
      contestId: id,
      defenseHash,
      wallet: w,
      winner: deployerAddress,
      reward: formatRtm(miningReward),
    };
  } catch (error) {
    // 失败回收：只告警，不掩盖原始异常；回收失败时提示人工处理。
    try {
      console.warn(`\nSmoke failed: ${error && error.message ? error.message : error}`);
      let id = contestId;
      if (!id) {
        try {
          const active = await arena.activeDefenseHash(defenseHash);
          if (active !== ethers.ZeroHash) id = active;
        } catch (lookupError) {
          console.warn(
            `  recovery: activeDefenseHash lookup failed: ` +
              `${lookupError && lookupError.message ? lookupError.message : lookupError}`
          );
        }
      }

      if (id) {
        const state = await arena.contestState(id);
        const info = await arena.contestInfo(id);
        if (state === 1n && info.isMining) {
          const balance = await rtm.balanceOf(w);
          console.warn(
            `  recovery: contest ${id} is Live; retireMining returns ` +
              `${formatRtm(balance)} RTM from W to Treasury`
          );
          const receipt = await (await arena.retireMining(id)).wait();
          if (!receipt || receipt.status !== 1) {
            console.warn(
              '  recovery: retireMining reverted; manual recovery required (see deploy/README.md)'
            );
          } else {
            console.warn(
              `  recovery: retireMining tx ${receipt.hash}; W balance now ` +
                `${formatRtm(await rtm.balanceOf(w))} RTM`
            );
          }
        } else {
          console.warn(
            `  recovery: contest state=${state} isMining=${info.isMining}; ` +
              'already ended/settled, no retire required'
          );
        }
      } else if (prefunded) {
        const balance = await rtm.balanceOf(w);
        const stillTarget = await rtm.isTarget(w);
        if (stillTarget) {
          console.warn(
            '  recovery: W is still a registered target; manual operator retireMining required ' +
              '(see deploy/README.md)'
          );
        } else if (balance > 0n) {
          console.warn(
            `  recovery: create did not register W; W refunds ${formatRtm(balance)} RTM to Treasury`
          );
          const receipt = await (
            await rtm.connect(wallet).transfer(treasuryAddress, balance, { gasPrice: 0 })
          ).wait();
          if (!receipt || receipt.status !== 1) {
            console.warn(
              '  recovery: W refund transfer reverted; manual recovery required (see deploy/README.md)'
            );
          } else {
            console.warn(`  recovery: W refund tx ${receipt.hash}`);
          }
        } else {
          console.warn('  recovery: W balance is 0; no refund required');
        }
      } else {
        console.warn('  recovery: no pre-fund was made; nothing to recover');
      }
    } catch (recoveryError) {
      console.warn(
        `  recovery failed: ` +
          `${recoveryError && recoveryError.message ? recoveryError.message : recoveryError}. ` +
          'Manual recovery required; see deploy/README.md.'
      );
    }
    throw error;
  } finally {
    // 只销毁 RPC provider；wallet（含私钥）随本函数作用域结束被丢弃。
    rpcProvider.destroy();
  }
}

async function main() {
  const allowRedeploy = process.env.DEPLOY_ALLOW_REDEPLOY === '1';
  if (fs.existsSync(ADDRESSES_FILE) && !allowRedeploy) {
    die(
      `${ADDRESSES_FILE} already exists; refusing to redeploy. ` +
        'Set DEPLOY_ALLOW_REDEPLOY=1 to deploy new contracts and overwrite the registry.'
    );
  }

  // chainId 守卫必须在任何部署之前：防止把 BESU_TESTNET_RPC 误指向本机 Anvil 8545。
  const network = await ethers.provider.getNetwork();
  if (network.chainId !== EXPECTED_CHAIN_ID) {
    die(
      `chainId guard failed: expected ${EXPECTED_CHAIN_ID} (${EXPECTED_CHAIN_ID_HEX}), ` +
        `got ${network.chainId}. Refusing to deploy; check BESU_TESTNET_RPC ` +
        '(this machine uses 8546 because 8545 is another project).'
    );
  }
  if (hre.network.name !== EXPECTED_NETWORK_NAME) {
    die(
      `network guard failed: expected "${EXPECTED_NETWORK_NAME}", ` +
        `got "${hre.network.name}". Run with --network ${EXPECTED_NETWORK_NAME}.`
    );
  }

  // Indexer start point: include the block before the first deployment so the
  // API can sync only the game's own history (especially on a public-chain fork).
  const deployBlock = await ethers.provider.getBlockNumber();

  const signers = await ethers.getSigners();
  if (signers.length === 0) die('no signer available; set BESU_TESTNET_KEY');
  const deployer = signers[0];
  const deployerAddress = ethers.getAddress(deployer.address);

  const platform = normalizeAddress(
    'PLATFORM_ADDRESS',
    process.env.PLATFORM_ADDRESS,
    deployerAddress
  );
  const operator = normalizeAddress(
    'OPERATOR_ADDRESS',
    process.env.OPERATOR_ADDRESS,
    deployerAddress
  );
  const faucetSignerExplicit = Boolean((process.env.FAUCET_SIGNER_ADDRESS || '').trim());
  const ticketSigner = normalizeAddress(
    'FAUCET_SIGNER_ADDRESS',
    process.env.FAUCET_SIGNER_ADDRESS,
    deployerAddress
  );
  const faucetDrip = parseAmount('FAUCET_DRIP_RTM', process.env.FAUCET_DRIP_RTM, '200');
  const faucetFunding = parseAmount(
    'FAUCET_FUND_RTM',
    process.env.FAUCET_FUND_RTM,
    '1000000'
  );
  const requestedMiningFund = parseAmount(
    'TREASURY_MINING_FUND',
    process.env.TREASURY_MINING_FUND,
    '3'
  );
  const refundAllowance = parseAmount(
    'TREASURY_ALLOWANCE_RTM',
    process.env.TREASURY_ALLOWANCE_RTM,
    '0',
    { allowZero: true }
  );
  const runSmoke = parseToggle('RUN_MINING_SMOKE', process.env.RUN_MINING_SMOKE, '1');

  if (runSmoke && operator !== deployerAddress) {
    die(
      'RUN_MINING_SMOKE=1 requires OPERATOR_ADDRESS == deployer because this script ' +
        'only holds BESU_TESTNET_KEY. Set RUN_MINING_SMOKE=0 to skip the on-chain smoke.'
    );
  }

  console.log(
    `network ${hre.network.name} chainId ${network.chainId} (${EXPECTED_CHAIN_ID_HEX})`
  );
  console.log(`deployer      ${deployerAddress}`);
  console.log(`platform      ${platform}`);
  console.log(`operator      ${operator}`);
  console.log(`ticketSigner  ${ticketSigner}`);
  console.log(
    `amounts       drip=${formatRtm(faucetDrip)} RTM ` +
      `faucetFund=${formatRtm(faucetFunding)} RTM ` +
      `miningFund=${formatRtm(requestedMiningFund)} RTM ` +
      `refundAllowance=${formatRtm(refundAllowance)} RTM`
  );
  console.log(`mining smoke  ${runSmoke ? 'enabled' : 'disabled'}`);

  if (platform !== deployerAddress && !faucetSignerExplicit) {
    console.warn('\nWARNING: PLATFORM_ADDRESS != deployer but FAUCET_SIGNER_ADDRESS is not set.');
    console.warn('         Faucet.ticketSigner is immutable and will remain the deployer.');
    console.warn('         Set FAUCET_SIGNER_ADDRESS explicitly for production.\n');
  }

  console.log('\nDeploying contracts...');
  const treasury = await deploy('Treasury', [deployerAddress]);
  const treasuryAddress = await treasury.getAddress();
  const arena = await deploy('Arena', [
    deployerAddress,
    treasuryAddress,
    true, // testnet=true：启用 mintForTest 与挖矿注水
  ]);
  const arenaAddress = await arena.getAddress();
  const rtm = await deploy('RTMToken', [deployerAddress, arenaAddress]);
  const rtmAddress = await rtm.getAddress();

  console.log('\nWiring...');
  await send('arena.initialize(rtm)', arena.initialize(rtmAddress));
  await send('arena.setOperator(operator)', arena.setOperator(operator));
  // BYOA 委托任务存根必须在任何 createByoaContest 之前绑定；不影响普通/挖矿赛。
  const taskSink = await deploy('TaskSink', [arenaAddress, rtmAddress]);
  const taskSinkAddress = await taskSink.getAddress();
  await send('arena.setTaskSink(taskSink)', arena.setTaskSink(taskSinkAddress));

  // Faucet/DataMarket 在 Arena 初始化后部署，参数固定且不可变。
  const faucet = await deploy('Faucet', [
    deployerAddress,
    rtmAddress,
    ticketSigner,
    faucetDrip,
  ]);
  const faucetAddress = await faucet.getAddress();
  const market = await deploy('DataMarket', [
    deployerAddress,
    rtmAddress,
    arenaAddress,
    treasuryAddress,
  ]);
  const marketAddress = await market.getAddress();
  await send('market.setOperator(operator)', market.setOperator(operator));

  // 挖矿工作资金必须恰为 MINING_REWARD × MAX_ACTIVE_MINING（K=3 → 3 RTM）。
  const miningReward = await arena.MINING_REWARD();
  const maxActiveMining = await arena.MAX_ACTIVE_MINING();
  const miningFeeBps = await arena.MINING_FEE_BPS();
  if (miningReward !== ethers.parseEther('1')) {
    die(`unexpected MINING_REWARD ${miningReward}; expected 1 RTM`);
  }
  const treasuryMiningFund = miningReward * maxActiveMining;
  if (requestedMiningFund !== treasuryMiningFund) {
    die(
      `TREASURY_MINING_FUND must equal ${formatRtm(treasuryMiningFund)} RTM ` +
        `(MINING_REWARD × MAX_ACTIVE_MINING), got ${formatRtm(requestedMiningFund)} RTM`
    );
  }
  assertEq('arena.MINING_REWARD()', miningReward, ethers.parseEther('1'));
  assertEq('arena.MINING_FEE_BPS()', miningFeeBps, 50n);
  assertEq('arena.MAX_ACTIVE_MINING()', maxActiveMining, 3n);

  await send(
    `arena.mintForTest(faucet, ${formatRtm(faucetFunding)} RTM)`,
    arena.mintForTest(faucetAddress, faucetFunding)
  );
  await send(
    `arena.mintForTest(treasury, ${formatRtm(treasuryMiningFund)} RTM)`,
    arena.mintForTest(treasuryAddress, treasuryMiningFund)
  );
  await send(
    `treasury.approveSpender(rtm, arena, ${formatRtm(refundAllowance)} RTM)`,
    treasury.approveSpender(rtmAddress, arenaAddress, refundAllowance)
  );

  console.log('\nVerifying wiring before smoke...');
  assertAddressEq('rtm.minter()', await rtm.minter(), arenaAddress);
  assertAddressEq('rtm.arena()', await rtm.arena(), arenaAddress);
  assertAddressEq('arena.rtm()', await arena.rtm(), rtmAddress);
  assertEq('arena.testnet()', await arena.testnet(), true);
  assertAddressEq('arena.operator()', await arena.operator(), operator);
  assertAddressEq('arena.taskSink()', await arena.taskSink(), taskSinkAddress);
  assertAddressEq('rtm.taskSink()', await rtm.taskSink(), taskSinkAddress);
  assertAddressEq('market.operator()', await market.operator(), operator);
  assertAddressEq('faucet.ticketSigner()', await faucet.ticketSigner(), ticketSigner);
  assertEq('faucet.dripAmount()', await faucet.dripAmount(), faucetDrip);
  assertEq('rtm.balanceOf(faucet)', await rtm.balanceOf(faucetAddress), faucetFunding);
  assertEq(
    'rtm.balanceOf(treasury) before smoke',
    await rtm.balanceOf(treasuryAddress),
    treasuryMiningFund
  );
  assertEq(
    'rtm.totalSupply() before smoke',
    await rtm.totalSupply(),
    faucetFunding + treasuryMiningFund
  );
  assertEq(
    'rtm.allowance(treasury, arena)',
    await rtm.allowance(treasuryAddress, arenaAddress),
    refundAllowance
  );
  assertEq('arena.activeMiningCount() before smoke', await arena.activeMiningCount(), 0n);

  let smoke = null;
  if (runSmoke) {
    smoke = await runMiningSmoke({
      treasury,
      arena,
      rtm,
      deployerAddress,
      faucetFunding,
      treasuryMiningFund,
      miningReward,
      rpcUrl: (process.env.BESU_TESTNET_RPC || '').trim() || 'http://127.0.0.1:8546',
    });
  } else {
    console.log('\nMining smoke skipped (RUN_MINING_SMOKE=0).');
  }

  if (platform !== deployerAddress) {
    console.log(`\nTransferring ownership to platform ${platform}...`);
    await send(
      'Treasury.transferOwnership(platform)',
      treasury.transferOwnership(platform)
    );
    await send('Arena.transferOwnership(platform)', arena.transferOwnership(platform));
    await send('RTMToken.transferOwnership(platform)', rtm.transferOwnership(platform));
    await send('Faucet.transferOwnership(platform)', faucet.transferOwnership(platform));
    await send('DataMarket.transferOwnership(platform)', market.transferOwnership(platform));
  } else {
    console.log('\nplatform == deployer; ownership stays with deployer.');
  }

  console.log('\nVerifying final wiring...');
  assertAddressEq('rtm.minter()', await rtm.minter(), arenaAddress);
  assertAddressEq('rtm.arena()', await rtm.arena(), arenaAddress);
  assertAddressEq('arena.rtm()', await arena.rtm(), rtmAddress);
  assertEq('arena.testnet()', await arena.testnet(), true);
  assertAddressEq('arena.operator()', await arena.operator(), operator);
  assertAddressEq('arena.taskSink()', await arena.taskSink(), taskSinkAddress);
  assertAddressEq('rtm.taskSink()', await rtm.taskSink(), taskSinkAddress);
  assertAddressEq('market.operator()', await market.operator(), operator);
  assertAddressEq('faucet.ticketSigner()', await faucet.ticketSigner(), ticketSigner);
  assertEq('faucet.dripAmount()', await faucet.dripAmount(), faucetDrip);
  assertAddressEq('treasury.owner()', await treasury.owner(), platform);
  assertAddressEq('arena.owner()', await arena.owner(), platform);
  assertAddressEq('rtm.owner()', await rtm.owner(), platform);
  assertAddressEq('faucet.owner()', await faucet.owner(), platform);
  assertAddressEq('market.owner()', await market.owner(), platform);
  assertEq('rtm.balanceOf(faucet)', await rtm.balanceOf(faucetAddress), faucetFunding);
  assertEq(
    'rtm.balanceOf(treasury)',
    await rtm.balanceOf(treasuryAddress),
    treasuryMiningFund
  );
  assertEq(
    'rtm.allowance(treasury, arena)',
    await rtm.allowance(treasuryAddress, arenaAddress),
    refundAllowance
  );
  assertEq('arena.activeMiningCount()', await arena.activeMiningCount(), 0n);

  const totalSupply = await rtm.totalSupply();
  const expectedTotalSupply =
    faucetFunding + treasuryMiningFund + (smoke ? miningReward : 0n);
  assertEq('rtm.totalSupply()', totalSupply, expectedTotalSupply);

  const registry = {
    network: hre.network.name,
    chainId: Number(network.chainId),
    rpc: hre.network.config.url || '',
    deployBlock,
    deployer: deployerAddress,
    platform,
    operator,
    ticketSigner,
    treasury: treasuryAddress,
    arena: arenaAddress,
    rtm: rtmAddress,
    faucet: faucetAddress,
    dataMarket: marketAddress,
    taskSink: taskSinkAddress,
    faucetDrip: formatRtm(faucetDrip),
    faucetFunding: formatRtm(faucetFunding),
    treasuryMiningFund: formatRtm(treasuryMiningFund),
    refundAllowance: formatRtm(refundAllowance),
    miningReward: formatRtm(miningReward),
    miningFeeBps: Number(miningFeeBps),
    totalSupply: formatRtm(totalSupply),
    smokeMining: smoke !== null,
    smokeDefenseHash: smoke ? smoke.defenseHash : null,
    smokeContestId: smoke ? smoke.contestId : null,
    smokeTxHash: smoke ? smoke.txHash : null,
    deployedAt: new Date().toISOString(),
  };

  // 只有部署、烟测、owner 转移和全部断言均成功后才写登记文件；
  // 任何失败都会退出，已存在的 addresses.json 保持不变。
  fs.writeFileSync(
    ADDRESSES_FILE,
    `${JSON.stringify(registry, null, 2)}\n`,
    'utf8'
  );

  console.log(`\nAll checks passed. Address registry written to ${ADDRESSES_FILE}`);
  if (smoke) {
    console.log(`Mining smoke settlement tx: ${smoke.txHash}`);
    console.log(`Mining smoke retired hash:  ${smoke.defenseHash}`);
  }
  console.log(
    JSON.stringify(
      {
        treasury: registry.treasury,
        arena: registry.arena,
        rtm: registry.rtm,
        faucet: registry.faucet,
        dataMarket: registry.dataMarket,
        taskSink: registry.taskSink,
        totalSupply: registry.totalSupply,
      },
      null,
      2
    )
  );
}

main().catch((error) => {
  console.error(
    `\nDeployment failed: ${error && error.message ? error.message : error}`
  );
  process.exit(1);
});
