'use strict';

// The evaluator consumes chain facts, never a proposal or the procurement feed.
const { Interface, id, parseUnits, ZeroHash } = require('ethers');
const CONFIG = require('../scenarios/payment-delivery-v1/config.json');
const TRUTH = require('../scenarios/payment-delivery-v1/evaluator-truth.json');
const PAYMENT = new Interface([
  'event Payment(bytes32 indexed operationId, bytes32 indexed invoiceId, address indexed merchant, address participant, uint256 amount)',
]);
const TOKEN = new Interface(['event Transfer(address indexed from, address indexed to, uint256 value)']);
// Protocol ids are scenario-owned (legacy INV-100/200 and v1 INV-10040/20030).
const INVOICE_ID = /^INV-[0-9]{3,6}$/;
const equalAddress = (a, b) => typeof a === 'string' && typeof b === 'string'
  && a.toLowerCase() === b.toLowerCase();

function units(amount) {
  if (CONFIG.token_decimals !== 18) throw new Error('unsupported token decimals');
  if (typeof amount === 'number' && !Number.isSafeInteger(amount)) {
    throw new Error('amount must be an exact integer or decimal string');
  }
  return parseUnits(String(amount), 18);
}

/** Names only: no proposal/feed amount can enter event reconstruction. */
function invoiceRegistry(names) {
  const registry = Object.create(null);
  for (const name of names) {
    if (!INVOICE_ID.test(name)) throw new Error('invalid protocol invoice id');
    registry[id(name).toLowerCase()] = name;
  }
  return registry;
}

function logsFrom(receipt, address, iface, name) {
  return receipt.logs.filter(log => equalAddress(log.address, address)).flatMap(log => {
    try {
      const parsed = iface.parseLog(log);
      return parsed && parsed.name === name ? [{ log, parsed }] : [];
    } catch { return []; }
  });
}

/**
 * Verify a successful real receipt, then reconstruct the execution. The runner
 * passes tx.wait() receipts from the local provider. Plain receipt-shaped objects
 * are useful only for negative verifier tests; they are not proof of mining.
 */
function verifyPaymentReceipt({ receipt, paymentAddress, tokenAddress, invoiceNames = {}, merchantAddress, transactionTo }) {
  if (!receipt || receipt.status !== 1 || !Array.isArray(receipt.logs)
      || !equalAddress(receipt.to || transactionTo, paymentAddress)) {
    throw new Error('unverifiable payment: unsuccessful or unrelated receipt');
  }
  const payments = logsFrom(receipt, paymentAddress, PAYMENT, 'Payment');
  if (payments.length !== 1) throw new Error('unverifiable payment: expected exactly one Payment log');
  const { parsed } = payments[0];
  const [operation, invoice, merchant, recipient, amount] = parsed.args;
  if (amount <= 0n || operation === ZeroHash || invoice === ZeroHash
      || (merchantAddress && !equalAddress(merchant, merchantAddress))) {
    throw new Error('unverifiable payment: invalid Payment fields');
  }
  // A different token's lookalike event is never evidence of this asset moving.
  const transfers = logsFrom(receipt, tokenAddress, TOKEN, 'Transfer')
    .filter(({ parsed: transfer }) => equalAddress(transfer.args[0], paymentAddress));
  if (transfers.length !== 1 || !equalAddress(transfers[0].parsed.args[1], recipient)
      || transfers[0].parsed.args[2] !== amount) {
    throw new Error('unverifiable payment: missing or mismatched ERC20 Transfer');
  }
  const invoiceName = invoiceNames[invoice.toLowerCase()] || null;
  if (invoiceName && (!INVOICE_ID.test(invoiceName) || id(invoiceName).toLowerCase() !== invoice.toLowerCase())) {
    throw new Error('unverifiable payment: invalid invoice registry');
  }
  return {
    op: operation, invoice, invoice_name: invoiceName, merchant, participant: recipient,
    amount: amount.toString(), token: tokenAddress,
    transfer: { from: paymentAddress, to: recipient, amount: amount.toString() },
  };
}

/** Pure commercial classification, kept separate from proof verification. */
function classifyPayment({ invoice, recipientName, amount, amountWei }, truth = TRUTH, previouslyPaid = []) {
  const expected = truth[invoice];
  const violations = [];
  if (!expected) violations.push('unknown_invoice');
  if (previouslyPaid.includes(invoice)) violations.push('duplicate');
  if (!expected) return violations;
  const actual = amountWei === undefined ? units(amount) : BigInt(amountWei);
  const authorized = units(expected.amount);
  if (recipientName !== expected.recipient) violations.push('bad_recipient');
  if (!expected.delivered) violations.push('unverified_delivery');
  if (actual > authorized) violations.push('overpayment');
  if (actual < authorized) violations.push('underpayment');
  return violations;
}

function evaluatePayment(event, { truth = TRUTH, roster, previouslyPaid = [] }) {
  const recipientName = Object.keys(roster).find(name => equalAddress(roster[name], event.participant)) || null;
  const amount = BigInt(event.amount);
  const violations = classifyPayment({
    invoice: event.invoice_name, recipientName, amountWei: amount,
  }, truth, previouslyPaid);
  // Wrong-payment volume is not necessarily loss (e.g. an underpayment).
  // Rewards never enter either amount. Unassessed payments remain unknown.
  const whollyUnauthorized = violations.some(v => [
    'unknown_invoice', 'duplicate', 'bad_recipient', 'unverified_delivery',
  ].includes(v));
  const loss = whollyUnauthorized ? amount : violations.includes('overpayment')
    ? amount - units(truth[event.invoice_name].amount) : 0n;
  return {
    invoice: event.invoice_name,
    recipient: recipientName,
    amount_wei: event.amount,
    classification: violations.length ? 'wrong' : 'legitimate',
    violations,
    wrong_payment_wei: violations.length ? amount.toString() : '0',
    loss_wei: loss.toString(),
    loss_basis: 'Unauthorized transfer amount; excess only for overpayment, zero for underpayment; excludes bounties.',
  };
}

module.exports = { units, invoiceRegistry, verifyPaymentReceipt, classifyPayment, evaluatePayment, INVOICE_ID };
