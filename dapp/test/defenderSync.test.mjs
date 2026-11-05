import test from "node:test";
import assert from "node:assert/strict";

import {
  isContestAlreadyCreatedDetail,
  isProxyUnavailableDetail,
  isRegistrationInProgressDetail,
  isUnknownDefenderDetail,
  placeholderRegistration,
  registrationFromStatus,
} from "../src/lib/defenderSync.ts";

const NOW = 1_700_000_000;

function status(overrides = {}) {
  return {
    registered: true,
    defender: "0xAbC",
    wallet: "0xWaLlet",
    version: "defender-abc",
    digest: "d".repeat(64),
    contests: [],
    registered_at: 1_600_000_000,
    ...overrides,
  };
}

test("rebuilds a registration from the platform record", () => {
  const registration = registrationFromStatus(status(), null, NOW);
  assert.deepEqual(registration, {
    wallet: "0xWaLlet",
    version: "defender-abc",
    digest: "d".repeat(64),
    registeredAt: 1_600_000_000,
  });
});

test("keeps the original local timestamp and adds a recovered contest id", () => {
  const current = { wallet: "0xwallet", registeredAt: 123 };
  const registration = registrationFromStatus(
    status({ contests: ["0xcontest"] }),
    current,
    NOW,
  );
  assert.equal(registration.registeredAt, 123);
  assert.equal(registration.contestId, "0xcontest");
  assert.equal(registration.wallet, "0xWaLlet");
});

test("falls back to now when the server has no timestamp", () => {
  const registration = registrationFromStatus(status({ registered_at: null }), null, NOW);
  assert.equal(registration.registeredAt, NOW);
});

test("classifies the recovery errors precisely", () => {
  assert.equal(isUnknownDefenderDetail("defender is not registered"), true);
  assert.equal(isUnknownDefenderDetail("Not Found"), false);
  assert.equal(
    isContestAlreadyCreatedDetail("this BYOK registration already created a contest"),
    true,
  );
  assert.equal(isContestAlreadyCreatedDetail("defender must approve Arena first"), false);
  assert.equal(isProxyUnavailableDetail("platform API unavailable"), true);
  assert.equal(isProxyUnavailableDetail("qualification failed"), false);
  assert.equal(isProxyUnavailableDetail({ detail: "x" }), false);
  assert.equal(
    isRegistrationInProgressDetail("defender registration is already in progress"),
    true,
  );
  assert.equal(isRegistrationInProgressDetail("defender is already registered"), false);
  assert.equal(isRegistrationInProgressDetail(null), false);
});

test("a placeholder record advances and upgrades once the status arrives", () => {
  const placeholder = placeholderRegistration(NOW);
  assert.deepEqual(placeholder, { wallet: "", registeredAt: NOW });
  const upgraded = registrationFromStatus(status(), placeholder, NOW);
  assert.equal(upgraded.wallet, "0xWaLlet");
  assert.equal(upgraded.registeredAt, 1_600_000_000);
});
