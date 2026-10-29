require('@nomicfoundation/hardhat-toolbox');
module.exports = {
  solidity: {
    version: '0.8.24',
    settings: {
      evmVersion: 'cancun',
      viaIR: true,
      optimizer: { enabled: true, runs: 200 }
    }
  },
  paths: { sources: './src' },
  networks: {
    hardhat: {},
    'besu-testnet': {
      url: process.env.BESU_TESTNET_RPC || 'http://127.0.0.1:8545',
      accounts: process.env.BESU_TESTNET_KEY ? [process.env.BESU_TESTNET_KEY] : [],
      chainId: 48850,
      gasPrice: 0,
      // Hardhat validates `gas` as a number or "auto" (not a hex string).
      // 0x1ffffffffffffe == 9007199254740990, below Number.MAX_SAFE_INTEGER.
      gas: 0x1ffffffffffffe,
      timeout: 120000
    }
  }
};
