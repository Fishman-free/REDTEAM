const { expect } = require('chai');
const { ethers, artifacts } = require('hardhat');
const { time, setCode } = require('@nomicfoundation/hardhat-network-helpers');

const POLICY_VERSION = ethers.id('redteam-flower-policy-v1');
const TYPES = {
  Consent: [
    { name: 'recipient', type: 'address' },
    { name: 'contributionId', type: 'bytes32' },
    { name: 'category', type: 'uint8' },
    { name: 'nonce', type: 'uint256' },
    { name: 'deadline', type: 'uint256' },
    { name: 'policyVersion', type: 'bytes32' },
  ],
};
const CATEGORY_NAMES = ['model finding', 'system finding', 'research contribution'];

function decodeMetadata(uri) {
  expect(uri).to.match(/^data:application\/json;base64,/);
  const json = Buffer.from(uri.split(',')[1], 'base64').toString('utf8');
  const metadata = JSON.parse(json);
  expect(metadata.image).to.match(/^data:image\/svg\+xml;base64,/);
  const svg = Buffer.from(metadata.image.split(',')[1], 'base64').toString('utf8');
  return { json, metadata, svg };
}

// EOA consent proves control of a key and acceptance of exact terms, not real identity.
describe('ContributionFlower recipient-consented soulbound recognition', function () {
  let flower, owner, issuer, recipient, otherRecipient, outsider, domain;

  beforeEach(async () => {
    [owner, issuer, recipient, otherRecipient, outsider] = await ethers.getSigners();
    flower = await (await ethers.getContractFactory('ContributionFlower')).deploy(owner.address, issuer.address);
    domain = {
      name: 'REDTEAM Flower', version: '1',
      chainId: (await ethers.provider.getNetwork()).chainId,
      verifyingContract: flower.target,
    };
  });

  async function consentFor(signer = recipient, overrides = {}) {
    return {
      recipient: signer.address,
      contributionId: ethers.id('flower-contribution'),
      category: 0,
      nonce: await flower.nonces(signer.address),
      deadline: await time.latest() + 3600,
      policyVersion: POLICY_VERSION,
      ...overrides,
    };
  }

  async function signed(signer = recipient, overrides = {}, domainOverrides = {}) {
    const consent = await consentFor(signer, overrides);
    return { consent, signature: await signer.signTypedData({ ...domain, ...domainOverrides }, TYPES, consent) };
  }

  async function issue(signer = recipient, overrides = {}) {
    const { consent, signature } = await signed(signer, overrides);
    await flower.connect(issuer).mint(consent, signature);
    return consent;
  }

  async function expectUnconsumed(consent) {
    expect(await flower.nonces(consent.recipient)).to.equal(0n);
    expect(await flower.contributionUsed(consent.contributionId)).to.equal(false);
    expect(await flower.nextTokenId()).to.equal(1n);
    expect(await flower.balanceOf(consent.recipient)).to.equal(0n);
  }

  describe('domain, interfaces and roles', function () {
    it('pins domain, name, policy, ERC721, metadata, ERC165 and ERC5192 interfaces', async () => {
      expect(await flower.name()).to.equal('REDTEAM Flower');
      expect(await flower.symbol()).to.equal('FLOWER');
      expect(await flower.owner()).to.equal(owner.address);
      expect(await flower.issuer()).to.equal(issuer.address);
      expect(await flower.POLICY_VERSION()).to.equal(POLICY_VERSION);
      expect(await flower.CONSENT_TYPEHASH()).to.equal(ethers.id(
        'Consent(address recipient,bytes32 contributionId,uint8 category,uint256 nonce,uint256 deadline,bytes32 policyVersion)'
      ));
      const actualDomain = await flower.eip712Domain();
      expect(actualDomain.name).to.equal(domain.name);
      expect(actualDomain.version).to.equal(domain.version);
      expect(actualDomain.chainId).to.equal(domain.chainId);
      expect(actualDomain.verifyingContract).to.equal(flower.target);
      for (const id of ['0x01ffc9a7', '0x80ac58cd', '0x5b5e139f', '0xb45a3c0e']) {
        expect(await flower.supportsInterface(id)).to.equal(true);
      }
      expect(await flower.supportsInterface('0xffffffff')).to.equal(false);
      expect(await flower.supportsInterface('0x00000000')).to.equal(false);
      expect(await flower.nextTokenId()).to.equal(1n);
      expect(await flower.nonces(recipient.address)).to.equal(0n);
    });

    it('rejects zero owner or issuer and emits initial issuer configuration', async () => {
      const factory = await ethers.getContractFactory('ContributionFlower');
      await expect(factory.deploy(ethers.ZeroAddress, issuer.address))
        .to.be.revertedWithCustomError(flower, 'OwnableInvalidOwner').withArgs(ethers.ZeroAddress);
      await expect(factory.deploy(owner.address, ethers.ZeroAddress))
        .to.be.revertedWithCustomError(flower, 'ZeroAddress');
      const fresh = await factory.deploy(owner.address, issuer.address);
      await expect(fresh.deploymentTransaction()).to.emit(fresh, 'IssuerUpdated')
        .withArgs(ethers.ZeroAddress, issuer.address);
    });

    it('mint is issuer-only even with valid recipient consent', async () => {
      const { consent, signature } = await signed();
      for (const caller of [owner, recipient, outsider]) {
        await expect(flower.connect(caller).mint(consent, signature))
          .to.be.revertedWithCustomError(flower, 'NotIssuer');
      }
      await expectUnconsumed(consent);
    });

    it('only owner can rotate issuer; old issuer loses all privileges without changing consent', async () => {
      const { consent, signature } = await signed();
      await issue(otherRecipient, { contributionId: ethers.id('before-rotation') });
      for (const caller of [issuer, recipient, outsider]) {
        await expect(flower.connect(caller).setIssuer(outsider.address))
          .to.be.revertedWithCustomError(flower, 'OwnableUnauthorizedAccount').withArgs(caller.address);
      }
      await expect(flower.setIssuer(ethers.ZeroAddress)).to.be.revertedWithCustomError(flower, 'ZeroAddress');
      await expect(flower.setIssuer(outsider.address)).to.emit(flower, 'IssuerUpdated')
        .withArgs(issuer.address, outsider.address);
      await expect(flower.connect(issuer).mint(consent, signature)).to.be.revertedWithCustomError(flower, 'NotIssuer');
      await expect(flower.connect(issuer).revoke(1)).to.be.revertedWithCustomError(flower, 'NotIssuer');
      await flower.connect(outsider).mint(consent, signature);
      await flower.connect(outsider).revoke(1);
      expect(await flower.revoked(1)).to.equal(true);
    });

    it('ownership handoff changes administration but never token ownership or issuer authority', async () => {
      await issue();
      await flower.transferOwnership(outsider.address);
      expect(await flower.ownerOf(1)).to.equal(recipient.address);
      expect(await flower.issuer()).to.equal(issuer.address);
      await expect(flower.setIssuer(owner.address)).to.be.revertedWithCustomError(flower, 'OwnableUnauthorizedAccount');
      await flower.connect(outsider).setIssuer(owner.address);
      await flower.connect(owner).revoke(1);
      expect(await flower.ownerOf(1)).to.equal(recipient.address);
    });
  });

  describe('consent validation and atomic issuance', function () {
    for (const category of [0, 1, 2]) {
      it(`mints category ${category}, emits lock/issuance and records exact immutable facts`, async () => {
        const { consent, signature } = await signed(recipient, { category });
        expect(await flower.connect(issuer).mint.staticCall(consent, signature)).to.equal(1n);
        const tx = await flower.connect(issuer).mint(consent, signature);
        await expect(tx).to.emit(flower, 'Transfer').withArgs(ethers.ZeroAddress, recipient.address, 1n);
        await expect(tx).to.emit(flower, 'Locked').withArgs(1n);
        await expect(tx).to.emit(flower, 'FlowerMinted')
          .withArgs(1n, recipient.address, consent.contributionId, category);
        const block = await ethers.provider.getBlock((await tx.wait()).blockNumber);
        expect(await flower.issuedAt(1)).to.equal(BigInt(block.timestamp));
        expect(await flower.ownerOf(1)).to.equal(recipient.address);
        expect(await flower.balanceOf(recipient.address)).to.equal(1n);
        expect(await flower.contributionIds(1)).to.equal(consent.contributionId);
        expect(await flower.categories(1)).to.equal(category);
        expect(await flower.contributionUsed(consent.contributionId)).to.equal(true);
        expect(await flower.revoked(1)).to.equal(false);
        expect(await flower.locked(1)).to.equal(true);
        expect(await flower.nonces(recipient.address)).to.equal(1n);
        expect(await flower.nextTokenId()).to.equal(2n);
      });
    }

    it('allocates sequential IDs with separate recipient nonce sequences', async () => {
      await issue();
      await issue(otherRecipient, { contributionId: ethers.id('second-wallet') });
      await issue(recipient, { contributionId: ethers.id('same-wallet-second') });
      expect(await flower.ownerOf(2)).to.equal(otherRecipient.address);
      expect(await flower.ownerOf(3)).to.equal(recipient.address);
      expect(await flower.nonces(recipient.address)).to.equal(2n);
      expect(await flower.nonces(otherRecipient.address)).to.equal(1n);
      expect(await flower.nextTokenId()).to.equal(4n);
    });

    for (const [label, overrides, error] of [
      ['zero recipient', { recipient: ethers.ZeroAddress }, 'ZeroAddress'],
      ['zero contribution ID', { contributionId: ethers.ZeroHash }, 'ZeroContributionId'],
      ['wrong policy', { policyVersion: ethers.id('other-policy') }, 'InvalidPolicyVersion'],
      ['zero policy', { policyVersion: ethers.ZeroHash }, 'InvalidPolicyVersion'],
      ['category 3', { category: 3 }, 'InvalidCategory'],
      ['category 255', { category: 255 }, 'InvalidCategory'],
      ['future nonce', { nonce: 1 }, 'InvalidNonce'],
    ]) {
      it(`rejects ${label} without consuming nonce, ID or serial number`, async () => {
        const { consent, signature } = await signed(recipient, overrides);
        await expect(flower.connect(issuer).mint(consent, signature)).to.be.revertedWithCustomError(flower, error);
        expect(await flower.nonces(recipient.address)).to.equal(0n);
        expect(await flower.nextTokenId()).to.equal(1n);
        expect(await flower.contributionUsed(consent.contributionId)).to.equal(false);
      });
    }

    it('rejects expired consent and accepts the exact deadline boundary', async () => {
      const expired = await signed(recipient, { deadline: await time.latest() - 1 });
      await expect(flower.connect(issuer).mint(expired.consent, expired.signature))
        .to.be.revertedWithCustomError(flower, 'ConsentExpired');
      await expectUnconsumed(expired.consent);
      const deadline = await time.latest() + 100;
      const valid = await signed(recipient, { deadline });
      await time.setNextBlockTimestamp(deadline);
      await flower.connect(issuer).mint(valid.consent, valid.signature);
      expect(await flower.issuedAt(1)).to.equal(deadline);
    });

    for (const [label, domainOverride] of [
      ['chain', () => ({ chainId: domain.chainId + 1n })],
      ['verifying contract', () => ({ verifyingContract: outsider.address })],
      ['domain name', () => ({ name: 'REDTEAM' })],
      ['domain version', () => ({ version: '2' })],
    ]) {
      it(`rejects a signature for the wrong ${label}`, async () => {
        const { consent, signature } = await signed(recipient, {}, domainOverride());
        await expect(flower.connect(issuer).mint(consent, signature)).to.be.revertedWithCustomError(flower, 'InvalidSignature');
        await expectUnconsumed(consent);
      });
    }

    it('rejects replay on a second deployed flower contract', async () => {
      const { consent, signature } = await signed();
      const second = await (await ethers.getContractFactory('ContributionFlower')).deploy(owner.address, issuer.address);
      await expect(second.connect(issuer).mint(consent, signature)).to.be.revertedWithCustomError(second, 'InvalidSignature');
      expect(await second.nonces(recipient.address)).to.equal(0n);
    });

    it('rejects issuer, owner and unrelated signer as substitutes for recipient consent', async () => {
      const consent = await consentFor();
      for (const signer of [issuer, owner, outsider]) {
        const signature = await signer.signTypedData(domain, TYPES, consent);
        await expect(flower.connect(issuer).mint(consent, signature)).to.be.revertedWithCustomError(flower, 'InvalidSignature');
      }
      await expectUnconsumed(consent);
    });

    it('rejects empty, malformed and malleable ECDSA signatures without state changes', async () => {
      const { consent, signature } = await signed();
      for (const invalid of ['0x', '0x1234']) {
        await expect(flower.connect(issuer).mint(consent, invalid))
          .to.be.revertedWithCustomError(flower, 'ECDSAInvalidSignatureLength');
      }
      const curveOrder = BigInt('0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141');
      const parsed = ethers.Signature.from(signature);
      const highS = ethers.concat([parsed.r, ethers.toBeHex(curveOrder - BigInt(parsed.s), 32),
        ethers.toBeHex(parsed.v === 27 ? 28 : 27, 1)]);
      await expect(flower.connect(issuer).mint(consent, highS)).to.be.revertedWithCustomError(flower, 'ECDSAInvalidSignatureS');
      await expectUnconsumed(consent);
    });

    for (const [field, value] of [
      ['recipient', () => otherRecipient.address],
      ['contributionId', () => ethers.id('altered-contribution')],
      ['category', () => 2],
      ['deadline', consent => consent.deadline + 100],
    ]) {
      it(`binds the signed ${field} and rejects tampering`, async () => {
        const { consent, signature } = await signed();
        await expect(flower.connect(issuer).mint({ ...consent, [field]: value(consent) }, signature))
          .to.be.revertedWithCustomError(flower, 'InvalidSignature');
        await expectUnconsumed(consent);
      });
    }

    it('rejects replay and stale nonces, then accepts a freshly signed next nonce', async () => {
      const { consent, signature } = await signed();
      await flower.connect(issuer).mint(consent, signature);
      await expect(flower.connect(issuer).mint(consent, signature)).to.be.revertedWithCustomError(flower, 'InvalidNonce');
      const stale = await signed(recipient, { contributionId: ethers.id('stale-nonce'), nonce: 0 });
      await expect(flower.connect(issuer).mint(stale.consent, stale.signature)).to.be.revertedWithCustomError(flower, 'InvalidNonce');
      expect(await flower.contributionUsed(stale.consent.contributionId)).to.equal(false);
      await issue(recipient, { contributionId: stale.consent.contributionId });
      expect(await flower.nextTokenId()).to.equal(3n);
    });

    it('allows only one of competing consents with the same recipient nonce', async () => {
      const first = await signed(recipient, { contributionId: ethers.id('nonce-race-first') });
      const second = await signed(recipient, { contributionId: ethers.id('nonce-race-second') });
      expect(first.consent.nonce).to.equal(second.consent.nonce);
      await flower.connect(issuer).mint(first.consent, first.signature);
      await expect(flower.connect(issuer).mint(second.consent, second.signature))
        .to.be.revertedWithCustomError(flower, 'InvalidNonce');
      expect(await flower.contributionUsed(second.consent.contributionId)).to.equal(false);
      expect(await flower.nextTokenId()).to.equal(2n);
      await issue(recipient, { contributionId: second.consent.contributionId });
      expect(await flower.nonces(recipient.address)).to.equal(2n);
    });

    it('deduplicates contribution IDs globally across recipients and categories', async () => {
      const consent = await issue();
      for (const signer of [recipient, otherRecipient]) {
        const duplicate = await signed(signer, { contributionId: consent.contributionId, category: 2 });
        await expect(flower.connect(issuer).mint(duplicate.consent, duplicate.signature))
          .to.be.revertedWithCustomError(flower, 'ContributionAlreadyUsed');
      }
      expect(await flower.nonces(otherRecipient.address)).to.equal(0n);
      expect(await flower.nonces(recipient.address)).to.equal(1n);
      expect(await flower.nextTokenId()).to.equal(2n);
    });

    it('rejects a malicious ERC721/ERC1271 receiver before any callback, even if it is issuer', async () => {
      const receiver = await (await ethers.getContractFactory('FlowerMaliciousReceiver')).deploy(flower.target);
      const { consent, signature } = await signed(recipient, { recipient: receiver.target });
      expect(await receiver.isValidSignature(ethers.ZeroHash, signature)).to.equal('0x1626ba7e');
      await expect(flower.connect(issuer).mint(consent, signature)).to.be.revertedWithCustomError(flower, 'ContractRecipient');
      await expectUnconsumed(consent);
      expect(await receiver.callbackCalled()).to.equal(false);
      await flower.setIssuer(receiver.target);
      await expect(receiver.attemptMint(consent, signature)).to.be.revertedWithCustomError(flower, 'ContractRecipient');
      await expectUnconsumed(consent);
      expect(await receiver.callbackCalled()).to.equal(false);
    });

    it('rejects a correctly signed recipient after code is installed at its address', async () => {
      const { consent, signature } = await signed();
      await setCode(recipient.address, '0x00');
      try {
        await expect(flower.connect(issuer).mint(consent, signature)).to.be.revertedWithCustomError(flower, 'ContractRecipient');
        await expectUnconsumed(consent);
      } finally {
        await setCode(recipient.address, '0x');
      }
      await flower.connect(issuer).mint(consent, signature);
      expect(await flower.ownerOf(1)).to.equal(recipient.address);
    });
  });

  describe('revocation permanence', function () {
    it('only issuer can revoke; nonexistent and already-revoked tokens fail', async () => {
      await expect(flower.connect(issuer).revoke(1)).to.be.revertedWithCustomError(flower, 'ERC721NonexistentToken').withArgs(1);
      await issue();
      for (const caller of [owner, recipient, outsider]) {
        await expect(flower.connect(caller).revoke(1)).to.be.revertedWithCustomError(flower, 'NotIssuer');
      }
      await expect(flower.connect(issuer).revoke(1)).to.emit(flower, 'FlowerRevoked').withArgs(1);
      await expect(flower.connect(issuer).revoke(1)).to.be.revertedWithCustomError(flower, 'AlreadyRevoked');
    });

    it('does not burn, unlock, reset nonce, clear dedupe, mutate issuance or reassign a revoked token', async () => {
      const consent = await issue();
      const issuedAt = await flower.issuedAt(1);
      const tx = await flower.connect(issuer).revoke(1);
      await expect(tx).not.to.emit(flower, 'Transfer');
      await expect(tx).not.to.emit(flower, 'Unlocked');
      expect(await flower.revoked(1)).to.equal(true);
      expect(await flower.locked(1)).to.equal(true);
      expect(await flower.ownerOf(1)).to.equal(recipient.address);
      expect(await flower.balanceOf(recipient.address)).to.equal(1n);
      expect(await flower.nonces(recipient.address)).to.equal(1n);
      expect(await flower.contributionUsed(consent.contributionId)).to.equal(true);
      expect(await flower.contributionIds(1)).to.equal(consent.contributionId);
      expect(await flower.categories(1)).to.equal(0n);
      expect(await flower.issuedAt(1)).to.equal(issuedAt);
      for (const signer of [recipient, otherRecipient]) {
        const duplicate = await signed(signer);
        await expect(flower.connect(issuer).mint(duplicate.consent, duplicate.signature))
          .to.be.revertedWithCustomError(flower, 'ContributionAlreadyUsed');
      }
      await issue(otherRecipient, { contributionId: ethers.id('after-revocation') });
      expect(await flower.ownerOf(2)).to.equal(otherRecipient.address);
      expect(await flower.ownerOf(1)).to.equal(recipient.address);
    });
  });

  describe('all transfer and approval paths are disabled', function () {
    for (const isRevoked of [false, true]) {
      it(`rejects all callers, safe overloads, self-transfer and burn destinations (${isRevoked ? 'revoked' : 'active'})`, async () => {
        await issue();
        if (isRevoked) await flower.connect(issuer).revoke(1);
        for (const caller of [recipient, owner, issuer, outsider]) {
          const connected = flower.connect(caller);
          for (const to of [otherRecipient.address, recipient.address, ethers.ZeroAddress]) {
            await expect(connected.transferFrom(recipient.address, to, 1)).to.be.revertedWithCustomError(flower, 'NonTransferable');
            await expect(connected['safeTransferFrom(address,address,uint256)'](recipient.address, to, 1))
              .to.be.revertedWithCustomError(flower, 'NonTransferable');
            await expect(connected['safeTransferFrom(address,address,uint256,bytes)'](recipient.address, to, 1, '0x1234'))
              .to.be.revertedWithCustomError(flower, 'NonTransferable');
          }
          for (const tokenId of [1, 999]) {
            await expect(connected.approve(outsider.address, tokenId)).to.be.revertedWithCustomError(flower, 'ApprovalsDisabled');
            await expect(connected.approve(ethers.ZeroAddress, tokenId)).to.be.revertedWithCustomError(flower, 'ApprovalsDisabled');
          }
          for (const approved of [true, false]) {
            await expect(connected.setApprovalForAll(outsider.address, approved)).to.be.revertedWithCustomError(flower, 'ApprovalsDisabled');
          }
        }
        expect(await flower.getApproved(1)).to.equal(ethers.ZeroAddress);
        expect(await flower.isApprovedForAll(recipient.address, outsider.address)).to.equal(false);
        expect(await flower.ownerOf(1)).to.equal(recipient.address);
        expect(await flower.balanceOf(otherRecipient.address)).to.equal(0n);
      });
    }

    it('rejects nonexistent-token transfers rather than allowing a mint via transfer', async () => {
      await expect(flower.transferFrom(ethers.ZeroAddress, recipient.address, 999))
        .to.be.revertedWithCustomError(flower, 'NonTransferable');
      await expect(flower['safeTransferFrom(address,address,uint256)'](ethers.ZeroAddress, recipient.address, 999))
        .to.be.revertedWithCustomError(flower, 'NonTransferable');
      await expect(flower['safeTransferFrom(address,address,uint256,bytes)'](ethers.ZeroAddress, recipient.address, 999, '0x'))
        .to.be.revertedWithCustomError(flower, 'NonTransferable');
    });

    it('bottom-level hook blocks burns, reassignment, remint and injected authorized operators', async () => {
      const harness = await (await ethers.getContractFactory('FlowerHarness')).deploy(owner.address, issuer.address);
      const consent = await consentFor();
      const signature = await recipient.signTypedData({ ...domain, verifyingContract: harness.target }, TYPES, consent);
      await harness.connect(issuer).mint(consent, signature);
      await harness.injectApproval(outsider.address, 1);
      await harness.injectOperator(recipient.address, owner.address);
      expect(await harness.getApproved(1)).to.equal(outsider.address);
      expect(await harness.isApprovedForAll(recipient.address, owner.address)).to.equal(true);
      for (const auth of [ethers.ZeroAddress, recipient.address, outsider.address, owner.address, issuer.address]) {
        await expect(harness.exposedTransfer(otherRecipient.address, 1, auth)).to.be.revertedWithCustomError(harness, 'NonTransferable');
        await expect(harness.exposedTransfer(recipient.address, 1, auth)).to.be.revertedWithCustomError(harness, 'NonTransferable');
        await expect(harness.exposedTransfer(ethers.ZeroAddress, 1, auth)).to.be.revertedWithCustomError(harness, 'NonTransferable');
      }
      await expect(harness.exposedBurn(1)).to.be.revertedWithCustomError(harness, 'NonTransferable');
      await expect(harness.exposedMint(otherRecipient.address, 1)).to.be.revertedWithCustomError(harness, 'NonTransferable');
      await harness.connect(issuer).revoke(1);
      await expect(harness.exposedBurn(1)).to.be.revertedWithCustomError(harness, 'NonTransferable');
      await expect(harness.exposedTransfer(otherRecipient.address, 1, ethers.ZeroAddress))
        .to.be.revertedWithCustomError(harness, 'NonTransferable');
      expect(await harness.ownerOf(1)).to.equal(recipient.address);
      expect(await harness.balanceOf(recipient.address)).to.equal(1n);
    });
  });

  describe('on-chain metadata, privacy and restricted API', function () {
    it('requires token existence for metadata and ERC5192 locked queries', async () => {
      for (const tokenId of [0, 1, 999]) {
        await expect(flower.tokenURI(tokenId)).to.be.revertedWithCustomError(flower, 'ERC721NonexistentToken').withArgs(tokenId);
        await expect(flower.locked(tokenId)).to.be.revertedWithCustomError(flower, 'ERC721NonexistentToken').withArgs(tokenId);
      }
    });

    it('decodes JSON and static SVG for all categories without any wallet or raw digest', async () => {
      let fixedImage;
      for (const category of [0, 1, 2]) {
        const consent = await issue(recipient, { category, contributionId: ethers.id(`metadata-${category}`) });
        const { json, metadata, svg } = decodeMetadata(await flower.tokenURI(category + 1));
        expect(metadata.name).to.equal(`REDTEAM Flower #${category + 1}`);
        expect(metadata.attributes).to.deep.equal([
          { trait_type: 'Token number', value: category + 1 },
          { trait_type: 'Category', value: CATEGORY_NAMES[category] },
          { trait_type: 'Status', value: 'active' },
        ]);
        expect(svg).to.match(/^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/);
        expect(svg).to.include('<ellipse');
        expect(svg).to.match(/<\/svg>$/);
        expect(svg).not.to.match(/<script|foreignObject|onload|href=|<image|<text/i);
        for (const sensitive of [recipient.address, owner.address, issuer.address, flower.target, consent.contributionId]) {
          expect((json + svg).toLowerCase()).not.to.include(sensitive.toLowerCase());
          expect((json + svg).toLowerCase()).not.to.include(sensitive.slice(2).toLowerCase());
        }
        expect(json).not.to.match(/contributionId|recipient|wallet|external_url/);
        if (fixedImage) expect(metadata.image).to.equal(fixedImage);
        fixedImage = metadata.image;
      }
    });

    it('revocation changes only metadata status; artwork, all other fields and schema stay fixed', async () => {
      await issue();
      const before = decodeMetadata(await flower.tokenURI(1));
      await time.increase(100);
      await flower.setIssuer(outsider.address);
      expect(await flower.tokenURI(1)).to.equal('data:application/json;base64,' + Buffer.from(before.json).toString('base64'));
      await flower.connect(outsider).revoke(1);
      const after = decodeMetadata(await flower.tokenURI(1));
      expect(after.metadata.attributes[2]).to.deep.equal({ trait_type: 'Status', value: 'revoked' });
      expect(after.svg).to.equal(before.svg);
      const expected = structuredClone(before.metadata);
      expected.attributes[2].value = 'revoked';
      expect(after.metadata).to.deep.equal(expected);
      expect(await flower.locked(1)).to.equal(true);
    });

    it('has no payable, burn, payout, URI setter, arbitrary-art or token-reassignment API', async () => {
      const artifact = await artifacts.readArtifact('ContributionFlower');
      expect(artifact.abi.some(entry => entry.stateMutability === 'payable')).to.equal(false);
      const functionNames = artifact.abi.filter(entry => entry.type === 'function').map(entry => entry.name);
      for (const forbidden of ['burn', 'unrevoke', 'unlock', 'setTokenURI', 'setBaseURI', 'setPolicyVersion',
        'setCategory', 'setArtwork', 'reassign', 'withdraw', 'payout', 'upgradeTo', 'initialize']) {
        expect(functionNames).not.to.include(forbidden);
      }
      await expect(owner.sendTransaction({ to: flower.target, value: 1 })).to.be.reverted;
      const { consent, signature } = await signed();
      await expect(flower.connect(issuer).mint(consent, signature, { value: 1 })).to.be.reverted;
      await expectUnconsumed(consent);
    });
  });
});
