// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
contract RewardSettlement {
 IERC20 public immutable token; address public immutable evaluator; uint256 public immutable cap; uint256 public paid;
 mapping(bytes32=>bool) public settled;
 struct Settlement { address beneficiary; uint256 reward; bool configured; }
 mapping(bytes32=>Settlement) public settlements;
 event Reward(bytes32 indexed settlementId,address indexed recipient,uint256 amount);
 modifier onlyEvaluator(){require(msg.sender==evaluator,"not evaluator");_;}
 constructor(IERC20 t,uint256 c){token=t;evaluator=msg.sender;cap=c;}
 function configureSettlement(bytes32 id,address beneficiary,uint256 reward) external onlyEvaluator { require(id!=bytes32(0)&&beneficiary!=address(0),"zero address"); require(reward>0&&reward<=cap,"cap"); require(!settlements[id].configured,"settlement configured"); settlements[id]=Settlement(beneficiary,reward,true); }
 function settle(bytes32 id,address recipient,uint256 amount) external onlyEvaluator { Settlement memory s=settlements[id]; require(s.configured&&s.beneficiary==recipient&&s.reward==amount,"settlement mismatch"); require(!settled[id],"already settled");require(paid+amount<=cap,"cap");settled[id]=true;paid+=amount;require(token.transfer(recipient,amount),"transfer failed");emit Reward(id,recipient,amount);}
}
