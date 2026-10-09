const { expect } = require('chai');
const fs = require('node:fs');
const path = require('node:path');

const exportPath = path.resolve(__dirname, '../../docs/site/flower-demo.json');

function publicKeys(value) {
  if (!value || typeof value !== 'object') return [];
  return Object.entries(value).flatMap(([key, item]) => [key, ...publicKeys(item)]);
}

function attributes(metadata) {
  return Object.fromEntries(metadata.attributes.map(({ trait_type, value }) => [trait_type, value]));
}

describe('Flower public demonstration export', function () {
  let demo;

  before(function () {
    demo = JSON.parse(fs.readFileSync(exportPath, 'utf8'));
  });

  it('labels the artifact as synthetic nonforked local-chain snapshots', function () {
    expect(demo.protocol).to.equal('redteam-flower-demo-v1');
    expect(demo.synthetic).to.equal(true);
    expect(demo.network).to.deep.equal({ name: 'hardhat', chainId: 31337, forked: false });
    expect(demo.contractAddress).to.match(/^0x[0-9a-fA-F]{40}$/);
    expect(demo.checks.transferBlocked).to.equal(true);
    expect(demo.checks.approvalsBlocked).to.equal(true);
  });

  it('records issuance and revocation of one NFT, not two distinct assets', function () {
    expect(demo.snapshots).to.have.length(2);
    const [issued, revoked] = demo.snapshots;
    expect(issued.label).to.equal('issued');
    expect(revoked.label).to.equal('revoked');
    expect(issued.tokenId).to.match(/^[1-9][0-9]*$/);
    expect(revoked.tokenId).to.equal(issued.tokenId);
    expect(issued.revoked).to.equal(false);
    expect(revoked.revoked).to.equal(true);
    expect(attributes(issued.metadata).Status).to.equal('active');
    expect(attributes(revoked.metadata).Status).to.equal('revoked');
    expect(issued.metadata.image).to.equal(revoked.metadata.image);
    expect(attributes(issued.metadata).Category).to.equal(attributes(revoked.metadata).Category);
  });

  it('does not export identity, consent signatures, local paths or raw finding data', function () {
    const forbidden = /^(recipient|owner|issuer|signature|privateKey|mnemonic|evidence|evidenceRoot|reviewerReference|auditReference|contributionId|sha256|digest)$/i;
    expect(publicKeys(demo).filter((key) => forbidden.test(key))).to.deep.equal([]);
    expect(JSON.stringify(demo)).not.to.match(/[A-Z]:[\\/]|file:\/\/|BEGIN [A-Z ]*PRIVATE KEY/i);
    for (const { metadata } of demo.snapshots) {
      expect(JSON.stringify(metadata)).not.to.match(/0x[0-9a-fA-F]{40,64}/);
    }
  });

  it('uses self-contained static flower art rather than remote or executable SVG content', function () {
    for (const { metadata } of demo.snapshots) {
      expect(metadata.image).to.match(/^data:image\/svg\+xml;base64,[A-Za-z0-9+/]+=*$/);
      const svg = Buffer.from(metadata.image.split(',')[1], 'base64').toString('utf8');
      expect(svg).to.include('<svg');
      expect(svg).to.include('</svg>');
      expect(svg).not.to.match(/<\s*(script|foreignObject|iframe|image|use|a)\b|\bon\w+\s*=|\b(?:href|src)\s*=|url\s*\(|javascript:/i);
    }
  });
});
