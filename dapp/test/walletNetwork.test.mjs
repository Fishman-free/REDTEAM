import test from "node:test";
import assert from "node:assert/strict";

import {
  ARENA_CHAIN_ID,
  diagnoseWalletNetwork,
} from "../src/lib/walletNetwork.ts";

const hash = (value) => "0x" + BigInt(value).toString(16).padStart(64, "0");

function probe(overrides = {}) {
  return {
    walletChainId: async () => ARENA_CHAIN_ID,
    walletHead: async () => 100n,
    walletBlock: async (height) => ({ hash: hash(height) }),
    appHead: async () => 100n,
    appBlock: async (height) => ({ hash: hash(height) }),
    ...overrides,
  };
}

test("matching chain and block is ok", async () => {
  const result = await diagnoseWalletNetwork(probe());
  assert.equal(result.kind, "ok");
  assert.equal(result.height, 88n);
});

test("wrong chain id is reported separately", async () => {
  const result = await diagnoseWalletNetwork(
    probe({ walletChainId: async () => 56 }),
  );
  assert.deepEqual(result, {
    kind: "wallet-chain",
    actualChainId: 56,
    expectedChainId: ARENA_CHAIN_ID,
  });
});

test("an unreadable wallet chain id is a wallet RPC failure, not a fork", async () => {
  const result = await diagnoseWalletNetwork(
    probe({
      walletChainId: async () => {
        throw new Error("Failed to fetch https://arena.agenttrust.site/rpc");
      },
    }),
  );
  assert.equal(result.kind, "wallet-rpc");
  assert.match(result.error, /Failed to fetch/);
});

test("an unreadable wallet head is a wallet RPC failure", async () => {
  const result = await diagnoseWalletNetwork(
    probe({
      walletHead: async () => {
        throw new Error("Failed to fetch");
      },
    }),
  );
  assert.equal(result.kind, "wallet-rpc");
});

test("an unreadable app head is an app RPC failure, not a wallet problem", async () => {
  const result = await diagnoseWalletNetwork(
    probe({
      appHead: async () => {
        throw new Error("HTTP request failed.");
      },
    }),
  );
  assert.equal(result.kind, "app-rpc");
  assert.match(result.error, /HTTP request failed/);
});

test("different block hashes prove a fork", async () => {
  const result = await diagnoseWalletNetwork(
    probe({ walletBlock: async (height) => ({ hash: hash(height + 1n) }) }),
  );
  assert.equal(result.kind, "fork");
  assert.equal(result.height, 88n);
  assert.notEqual(result.walletHash, result.appHash);
});

test("a failed block comparison is inconclusive, not a fork", async () => {
  const result = await diagnoseWalletNetwork(
    probe({
      appBlock: async () => {
        throw new Error("timeout");
      },
    }),
  );
  assert.equal(result.kind, "unverified");
});

test("a missing wallet block is inconclusive", async () => {
  const result = await diagnoseWalletNetwork(
    probe({ walletBlock: async () => null }),
  );
  assert.equal(result.kind, "unverified");
});

test("chains with fewer than twelve blocks are accepted without a hash check", async () => {
  const result = await diagnoseWalletNetwork(
    probe({ walletHead: async () => 5n, appHead: async () => 5n }),
  );
  assert.equal(result.kind, "ok");
  assert.equal(result.height, null);
});

test("hash comparison is case insensitive", async () => {
  const result = await diagnoseWalletNetwork(
    probe({
      walletBlock: async (height) => ({ hash: hash(height).toUpperCase().replace("0X", "0x") }),
    }),
  );
  assert.equal(result.kind, "ok");
});
