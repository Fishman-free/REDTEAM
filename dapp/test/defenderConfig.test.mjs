import test from "node:test";
import assert from "node:assert/strict";

import { defenderConfigHash } from "../src/lib/defenderConfig.ts";

test("matches the backend v1 config hash", () => {
  assert.equal(
    defenderConfigHash("glm", "prompt", "mandate"),
    "0x8b1b510ab957e822d1aea8ef7d0ffc428daf7c275b691bb7a564fce12d4d06ec",
  );
});

test("custom endpoints extend the preimage", () => {
  assert.equal(
    defenderConfigHash(
      "glm",
      "prompt",
      "mandate",
      "https://models.example/v1",
      "my-model",
    ),
    "0x161930309546b13b1f2de13957ab0e2e68930342008b1a770118a7ecf92c81cb",
  );
  assert.notEqual(
    defenderConfigHash(
      "glm",
      "prompt",
      "mandate",
      "https://models.example/v1",
      "my-model",
    ),
    defenderConfigHash("glm", "prompt", "mandate"),
  );
});
