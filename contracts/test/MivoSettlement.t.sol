// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;
import {MivoSettlement} from "../src/MivoSettlement.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
interface Vm {
 function addr(uint256) external returns(address);
 function sign(uint256,bytes32) external returns(uint8,bytes32,bytes32);
 function prank(address) external;
 function expectRevert() external;
 function warp(uint256) external;
 function chainId(uint256) external;
}
contract MockUSD is ERC20 {
 constructor() ERC20("Mock USD","mUSD"){}
 function decimals() public pure override returns(uint8){return 6;}
 function mint(address to,uint256 amount) external {_mint(to,amount);}
}
contract SettlementTest {
 Vm constant vm=Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
 uint256 constant SIGNER_KEY=0xA11CE; // Public, test-only fixture; never funded or deployed.
 address buyer=address(0xB0B);address merchant=address(0xCAFE);
 MockUSD token;MivoSettlement settlement;
 function setUp() public {
  vm.chainId(31337);token=new MockUSD();settlement=new MivoSettlement(address(token),vm.addr(SIGNER_KEY),1000e6);
  token.mint(buyer,500e6);vm.prank(buyer);token.approve(address(settlement),500e6);
 }
 function auth() internal view returns(MivoSettlement.Authorization memory){return MivoSettlement.Authorization(keccak256("quote"),buyer,merchant,100e6,1,block.timestamp+600);}
 function sig(MivoSettlement.Authorization memory a) internal returns(bytes memory){(uint8 v,bytes32 r,bytes32 s)=vm.sign(SIGNER_KEY,settlement.digest(a));return abi.encodePacked(r,s,v);}
 function testSettlement() public {MivoSettlement.Authorization memory a=auth();bytes memory s=sig(a);vm.prank(buyer);settlement.settle(a,s);require(token.balanceOf(merchant)==100e6);require(settlement.paid(a.quoteId));}
 function testDuplicate() public {MivoSettlement.Authorization memory a=auth();bytes memory s=sig(a);vm.prank(buyer);settlement.settle(a,s);vm.expectRevert();vm.prank(buyer);settlement.settle(a,s);}
 function testWrongAmount() public {MivoSettlement.Authorization memory a=auth();bytes memory s=sig(a);a.amount++;vm.expectRevert();vm.prank(buyer);settlement.settle(a,s);}
 function testWrongMerchant() public {MivoSettlement.Authorization memory a=auth();bytes memory s=sig(a);a.merchant=address(0xDEAD);vm.expectRevert();vm.prank(buyer);settlement.settle(a,s);}
 function testWrongBuyer() public {MivoSettlement.Authorization memory a=auth();bytes memory s=sig(a);vm.expectRevert();settlement.settle(a,s);}
 function testExpired() public {MivoSettlement.Authorization memory a=auth();bytes memory s=sig(a);vm.warp(a.deadline);vm.expectRevert();vm.prank(buyer);settlement.settle(a,s);}
 function testWrongChain() public {MivoSettlement.Authorization memory a=auth();bytes memory s=sig(a);vm.chainId(5042002);vm.expectRevert();vm.prank(buyer);settlement.settle(a,s);}
 function testInvalidSignature() public {MivoSettlement.Authorization memory a=auth();vm.expectRevert();vm.prank(buyer);settlement.settle(a,hex"1234");}
 function testInsufficientBalance() public {MivoSettlement.Authorization memory a=auth();a.amount=600e6;bytes memory s=sig(a);vm.prank(buyer);token.approve(address(settlement),600e6);vm.expectRevert();vm.prank(buyer);settlement.settle(a,s);require(!settlement.paid(a.quoteId));}
 function testNoAllowance() public {MivoSettlement.Authorization memory a=auth();bytes memory s=sig(a);vm.prank(buyer);token.approve(address(settlement),0);vm.expectRevert();vm.prank(buyer);settlement.settle(a,s);}
 function testNonceReplay() public {MivoSettlement.Authorization memory a=auth();bytes memory s=sig(a);vm.prank(buyer);settlement.settle(a,s);a.quoteId=keccak256("other");s=sig(a);vm.expectRevert();vm.prank(buyer);settlement.settle(a,s);}
 function testSpendingCap() public {MivoSettlement.Authorization memory a=auth();a.amount=1001e6;bytes memory s=sig(a);vm.expectRevert();vm.prank(buyer);settlement.settle(a,s);}
}
