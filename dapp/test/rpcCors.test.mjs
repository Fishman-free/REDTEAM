import test from "node:test";
import assert from "node:assert/strict";

import { rpcCorsMiddleware } from "../lib/rpcCors.mjs";

function run({ method = "POST", origin, requestHeaders } = {}) {
  const headers = {};
  const req = {
    method,
    get(name) {
      if (name === "origin") return origin;
      if (name === "access-control-request-headers") return requestHeaders;
      return undefined;
    },
  };
  const res = {
    statusCode: 200,
    ended: false,
    setHeader(key, value) {
      headers[key] = value;
    },
    status(code) {
      this.statusCode = code;
      return this;
    },
    end() {
      this.ended = true;
    },
  };
  let nextCalled = false;
  rpcCorsMiddleware(req, res, () => {
    nextCalled = true;
  });
  return { headers, res, nextCalled };
}

test("extension preflight is answered locally with echoed origin", () => {
  const { headers, res, nextCalled } = run({
    method: "OPTIONS",
    origin: "chrome-extension://abcdef",
    requestHeaders: "content-type",
  });
  assert.equal(headers["Access-Control-Allow-Origin"], "chrome-extension://abcdef");
  assert.equal(headers["Access-Control-Allow-Credentials"], "true");
  assert.equal(headers["Access-Control-Allow-Headers"], "content-type");
  assert.match(headers["Access-Control-Allow-Methods"], /POST/);
  assert.equal(res.statusCode, 204);
  assert.equal(res.ended, true);
  assert.equal(nextCalled, false);
});

test("a normal RPC POST keeps the CORS headers and reaches the proxy", () => {
  const { headers, nextCalled } = run({
    origin: "chrome-extension://abcdef",
  });
  assert.equal(headers["Access-Control-Allow-Origin"], "chrome-extension://abcdef");
  assert.equal(headers["Access-Control-Allow-Headers"], "content-type, authorization");
  assert.equal(nextCalled, true);
});

test("same-origin and server-side calls without an Origin get no Allow-Origin", () => {
  const { headers, nextCalled } = run({});
  assert.equal(headers["Access-Control-Allow-Origin"], undefined);
  assert.equal("Access-Control-Allow-Credentials" in headers, false);
  assert.equal(nextCalled, true);
});
