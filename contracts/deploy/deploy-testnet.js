'use strict';

/**
 * RTM 红队游戏 —— 测试网五合约部署 + wiring + 地址登记。
 *
 * 运行（在 contracts/ 目录）：
 *   BESU_TESTNET_RPC=http://127.0.0.1:8546 \
 *   BESU_TESTNET_KEY="$(tr -d '\r\n' < ../infra/besu-testnet/keydir/key)" \
 *   npx hardhat run deploy/deploy-testnet.js --network besu-testnet
 *
 * 环境变量（全部有默认值，地址必须非零，金额必须 > 0）：
 *   PLATFORM_ADDRESS          默认 deployer；若与 deployer 不同，wiring 后转移全部 Ownable ownership
 *   OPERATOR_ADDRESS          默认 deployer
 *   FAUCET_SIGNER_ADDRESS     默认 deployer
 *   FAUCET_DRIP_RTM           默认 200
 *   FAUCET_FUND_RTM           默认 1000000
 *   TREASURY_ALLOWANCE_RTM    默认 1000000
 *   DEPLOY_ALLOW_REDEPLOY=1   允许覆盖已存在的 addresses.json
 *
 * 任何校验失败都会以非零退出码结束；addresses.json 只在全部 assert 通过后写入。
 * 本脚本绝不读取或打印私钥；私钥只经 Hardhat 的 BESU_TESTNET_KEY 注入。
 */

const fs = require('fs');
const path = require('path');
const hre = require('hardhat');

const { ethers } = hre;

const EXPECTED_CHAIN_ID = 48850n;
const EXPECTED_CHAIN_ID_HEX = '0xbed2';
const ADDRESSES_FILE = path.join(__dirname, 'addresses.json');

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

function parsePositiveAmount(name, value, fallback) {
  const raw = (value || '').trim() || fallback;
  let amount;
  try {
    amount = ethers.parseEther(raw);
  } catch {
    die(`${name} must be a decimal RTM amount (got "${raw}")`);
  }
  if (amount <= 0n) die(`${name} must be greater than zero`);
  return amount;
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
  if (got !== expected) die(`assert ${label}: expected ${expected}, got ${got}`);
  console.log(`  assert ${label} == ${expected}`);
}

function assertEq(label, actual, expected) {
  if (actual !== expected) {
    die(`assert ${label}: expected ${String(expected)}, got ${String(actual)}`);
  }
  console.log(`  assert ${label} == ${String(expected)}`);
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
  if (hre.network.name !== 'besu-testnet') {
    console.warn(
      `warning: network name is "${hre.network.name}", expected "besu-testnet"`
    );
  }

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
  const ticketSigner = normalizeAddress(
    'FAUCET_SIGNER_ADDRESS',
    process.env.FAUCET_SIGNER_ADDRESS,
    deployerAddress
  );
  const faucetDrip = parsePositiveAmount(
    'FAUCET_DRIP_RTM',
    process.env.FAUCET_DRIP_RTM,
    '200'
  );
  const faucetFunding = parsePositiveAmount(
    'FAUCET_FUND_RTM',
    process.env.FAUCET_FUND_RTM,
    '1000000'
  );
  const treasuryAllowance = parsePositiveAmount(
    'TREASURY_ALLOWANCE_RTM',
    process.env.TREASURY_ALLOWANCE_RTM,
    '1000000'
  );

  console.log(
    `network ${hre.network.name} chainId ${network.chainId} (${EXPECTED_CHAIN_ID_HEX})`
  );
  console.log(`deployer      ${deployerAddress}`);
  console.log(`platform      ${platform}`);
  console.log(`operator      ${operator}`);
  console.log(`ticketSigner  ${ticketSigner}`);
  console.log(
    `amounts       drip=${ethers.formatEther(faucetDrip)} RTM ` +
      `fund=${ethers.formatEther(faucetFunding)} RTM ` +
      `allowance=${ethers.formatEther(treasuryAllowance)} RTM`
  );

  console.log('\nDeploying contracts...');
  const treasury = await deploy('Treasury', [deployerAddress]);
  const arena = await deploy('Arena', [
    deployerAddress,
    await treasury.getAddress(),
    true, // testnet=true：启用 mintForTest
  ]);
  const rtm = await deploy('RTMToken', [
    deployerAddress,
    await arena.getAddress(),
  ]);
  const faucet = await deploy('Faucet', [
    deployerAddress,
    await rtm.getAddress(),
    ticketSigner,
    faucetDrip,
  ]);
  const market = await deploy('DataMarket', [
    deployerAddress,
    await rtm.getAddress(),
    await arena.getAddress(),
    await treasury.getAddress(),
  ]);

  const treasuryAddress = await treasury.getAddress();
  const arenaAddress = await arena.getAddress();
  const rtmAddress = await rtm.getAddress();
  const faucetAddress = await faucet.getAddress();
  const marketAddress = await market.getAddress();

  console.log('\nWiring...');
  await send('arena.initialize(rtm)', arena.initialize(rtmAddress));
  await send('arena.setOperator(operator)', arena.setOperator(operator));
  await send(
    'market.setOperator(operator)',
    market.setOperator(operator)
  );
  await send(
    'arena.mintForTest(faucet, faucetFunding)',
    arena.mintForTest(faucetAddress, faucetFunding)
  );
  await send(
    'treasury.approveSpender(rtm, arena, treasuryAllowance)',
    treasury.approveSpender(rtmAddress, arenaAddress, treasuryAllowance)
  );

  if (platform !== deployerAddress) {
    console.log(`\nTransferring ownership to platform ${platform}...`);
    await send(
      'Treasury.transferOwnership(platform)',
      treasury.transferOwnership(platform)
    );
    await send(
      'Arena.transferOwnership(platform)',
      arena.transferOwnership(platform)
    );
    await send(
      'RTMToken.transferOwnership(platform)',
      rtm.transferOwnership(platform)
    );
    await send(
      'Faucet.transferOwnership(platform)',
      faucet.transferOwnership(platform)
    );
    await send(
      'DataMarket.transferOwnership(platform)',
      market.transferOwnership(platform)
    );
  } else {
    console.log('\nplatform == deployer; ownership stays with deployer.');
  }

  console.log('\nVerifying wiring...');
  assertAddressEq('rtm.minter()', await rtm.minter(), arenaAddress);
  assertAddressEq('rtm.arena()', await rtm.arena(), arenaAddress);
  assertAddressEq('arena.rtm()', await arena.rtm(), rtmAddress);
  assertEq('arena.testnet()', await arena.testnet(), true);
  assertAddressEq('arena.operator()', await arena.operator(), operator);
  assertAddressEq('market.operator()', await market.operator(), operator);
  assertAddressEq('faucet.ticketSigner()', await faucet.ticketSigner(), ticketSigner);
  assertEq('faucet.dripAmount()', await faucet.dripAmount(), faucetDrip);
  assertAddressEq('treasury.owner()', await treasury.owner(), platform);
  assertAddressEq('arena.owner()', await arena.owner(), platform);
  assertAddressEq('rtm.owner()', await rtm.owner(), platform);
  assertAddressEq('faucet.owner()', await faucet.owner(), platform);
  assertAddressEq('market.owner()', await market.owner(), platform);
  assertEq(
    'rtm.balanceOf(faucet)',
    await rtm.balanceOf(faucetAddress),
    faucetFunding
  );
  assertEq('rtm.totalSupply()', await rtm.totalSupply(), faucetFunding);
  const allowance = await rtm.allowance(treasuryAddress, arenaAddress);
  if (allowance < treasuryAllowance) {
    die(
      `assert rtm.allowance(treasury, arena): expected >= ${treasuryAllowance}, ` +
        `got ${allowance}`
    );
  }
  console.log(`  assert rtm.allowance(treasury, arena) >= ${treasuryAllowance}`);
  assertEq('arena.activeMiningCount()', await arena.activeMiningCount(), 0n);

  const registry = {
    network: hre.network.name,
    chainId: Number(network.chainId),
    rpc: hre.network.config.url || '',
    deployer: deployerAddress,
    platform,
    operator,
    ticketSigner,
    treasury: treasuryAddress,
    arena: arenaAddress,
    rtm: rtmAddress,
    faucet: faucetAddress,
    dataMarket: marketAddress,
    faucetDrip: ethers.formatEther(faucetDrip),
    faucetFunding: ethers.formatEther(faucetFunding),
    treasuryAllowance: ethers.formatEther(treasuryAllowance),
    deployedAt: new Date().toISOString(),
  };

  fs.writeFileSync(
    ADDRESSES_FILE,
    `${JSON.stringify(registry, null, 2)}\n`,
    'utf8'
  );

  console.log(`\nAll checks passed. Address registry written to ${ADDRESSES_FILE}`);
  console.log(
    JSON.stringify(
      {
        treasury: registry.treasury,
        arena: registry.arena,
        rtm: registry.rtm,
        faucet: registry.faucet,
        dataMarket: registry.dataMarket,
      },
      null,
      2
    )
  );
}

main().catch((error) => {
  console.error(`\nDeployment failed: ${error && error.message ? error.message : error}`);
  process.exit(1);
});
