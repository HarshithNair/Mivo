// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @notice Testnet-only settlement of server-authorized, buyer-approved quotes.
/// @dev The buyer calls settle; exact ERC20 amount is sent directly to the merchant.
contract MivoSettlement is EIP712, ReentrancyGuard {
    using SafeERC20 for IERC20;
    struct Authorization {
        bytes32 quoteId;
        address buyer;
        address merchant;
        uint256 amount;
        uint256 nonce;
        uint256 deadline;
    }
    bytes32 public constant TYPEHASH = keccak256("Authorization(bytes32 quoteId,address buyer,address merchant,uint256 amount,uint256 nonce,uint256 deadline)");
    IERC20 public immutable token;
    address public immutable signer;
    uint256 public immutable spendingCap;
    mapping(bytes32 => bool) public paid;
    mapping(address => mapping(uint256 => bool)) public usedNonces;
    event Settled(bytes32 indexed quoteId, address indexed buyer, address indexed merchant, address token, uint256 amount, uint256 nonce);
    error InvalidAuthorization();
    error AlreadyPaid();
    error TransferMismatch();
    constructor(address token_, address signer_, uint256 cap_) EIP712("MivoSettlement", "1") {
        require(block.chainid == 31337 || block.chainid == 5042002, "Testnet only");
        require(token_.code.length > 0 && signer_ != address(0) && cap_ > 0, "Invalid configuration");
        token = IERC20(token_); signer = signer_; spendingCap = cap_;
    }
    function digest(Authorization calldata a) public view returns (bytes32) {
        return _hashTypedDataV4(keccak256(abi.encode(TYPEHASH,a.quoteId,a.buyer,a.merchant,a.amount,a.nonce,a.deadline)));
    }
    function settle(Authorization calldata a, bytes calldata signature) external nonReentrant {
        if (msg.sender != a.buyer || a.buyer == a.merchant || a.merchant == address(0) || a.quoteId == bytes32(0) || a.amount == 0 || a.amount > spendingCap || block.timestamp >= a.deadline) revert InvalidAuthorization();
        if (paid[a.quoteId] || usedNonces[a.buyer][a.nonce]) revert AlreadyPaid();
        if (ECDSA.recover(digest(a), signature) != signer) revert InvalidAuthorization();
        paid[a.quoteId] = true; usedNonces[a.buyer][a.nonce] = true;
        uint256 beforeBalance = token.balanceOf(a.merchant);
        token.safeTransferFrom(a.buyer, a.merchant, a.amount);
        if (token.balanceOf(a.merchant) - beforeBalance != a.amount) revert TransferMismatch();
        emit Settled(a.quoteId,a.buyer,a.merchant,address(token),a.amount,a.nonce);
    }
}
