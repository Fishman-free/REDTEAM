// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
contract PaymentAgent {
 IERC20 public immutable token; address public operator; uint256 public immutable maxPayment; uint256 public totalPaid;
 mapping(address=>bool) public allowlisted; mapping(bytes32=>bool) public used;
 struct Invoice { address merchant; address participant; uint256 amount; bool configured; }
 mapping(bytes32=>Invoice) public invoices;
 event Payment(bytes32 indexed operationId, bytes32 indexed invoiceId, address indexed merchant, address participant, uint256 amount);
 modifier onlyOperator(){require(msg.sender==operator,"not operator");_;}
 constructor(IERC20 t,uint256 cap){token=t; operator=msg.sender; maxPayment=cap;}
 function setAllowlisted(address a,bool ok) external onlyOperator { require(a!=address(0),"zero address"); allowlisted[a]=ok; }
 function configureInvoice(bytes32 id,address merchant,address participant,uint256 amount) external onlyOperator { require(id!=bytes32(0),"zero id"); require(allowlisted[merchant]&&allowlisted[participant],"not allowlisted"); require(amount>0&&amount<=maxPayment,"cap"); require(!invoices[id].configured,"invoice configured"); invoices[id]=Invoice(merchant,participant,amount,true); }
 function pay(bytes32 op,bytes32 invoice,address merchant,address participant,uint256 amount) external onlyOperator {
  Invoice memory i=invoices[invoice]; require(i.configured&&i.merchant==merchant&&i.participant==participant&&i.amount==amount,"invoice mismatch"); require(!used[op] && !used[invoice],"duplicate"); require(allowlisted[merchant]&&allowlisted[participant],"not allowlisted");
  require(totalPaid+amount<=maxPayment,"cap"); used[op]=true; used[invoice]=true; totalPaid+=amount;
  require(token.transfer(participant,amount),"transfer failed"); emit Payment(op,invoice,merchant,participant,amount);
 }
}
