'use client';
// Payments portal for Raspberry Pi BUY signals: approve in MetaMask, pay testnet USDC on Arc,
// and show the status the BACKEND reports after verifying the transaction on-chain.
// The page never decides a payment succeeded; it only displays what /api/buy-payments says.
import Link from 'next/link';
import {useEffect, useState} from 'react';
import {useAccount, useConnect, useDisconnect, usePublicClient, useSwitchChain, useWalletClient} from 'wagmi';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {encodeFunctionData, formatUnits, parseAbi, type Address, type Hex} from 'viem';
import {api, friendlyError} from '@/lib/api';
import {Button} from './ui/button';
import {arc} from './providers';
import s from './buy-payments.module.css';

const erc20 = parseAbi(['function transfer(address to,uint256 amount) returns (bool)', 'function balanceOf(address owner) view returns (uint256)']);
const USDC = '0x3600000000000000000000000000000000000000' as Address; // Arc Testnet USDC ERC-20 interface, 6 decimals
const FINAL = ['paid', 'failed', 'expired', 'rejected'];
const PENDING_KEY = 'mivo-buy-pending';

type Payment = {
  id: string; status: string; label: string; reason: string | null; product: string; dealer: string;
  amount_usdc: string; token_amount: string; token_address: Address; token_decimals: number; recipient: Address;
  payer: Address | null; chain_id: number; network: string; reference: Hex; tx_hash: Hex | null; explorer_url: string | null;
  block_number: number | null; created: number; expires: number; paid_at: number | null;
  events: {status: string; label: string; at: number; note: string | null}[];
};

const short = (a?: string | null) => (a ? `${a.slice(0, 8)}…${a.slice(-6)}` : '—');
const time = (t: number) => new Date(t * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});

function isRejection(error: unknown): boolean {
  // MetaMask: EIP-1193 code 4001; viem wraps it as UserRejectedRequestError somewhere in the cause chain.
  for (let e = error as {code?: number; name?: string; message?: string; cause?: unknown} | undefined, depth = 0; e && depth < 6; e = e.cause as typeof e, depth++) {
    if (e.code === 4001 || e.name === 'UserRejectedRequestError' || /user (rejected|denied)|rejected the request/i.test(e.message ?? '')) return true;
  }
  return false;
}

function loadPending(): Record<string, Hex> {
  try { return JSON.parse(localStorage.getItem(PENDING_KEY) || '{}'); } catch { return {}; }
}
function savePending(map: Record<string, Hex>) {
  try { localStorage.setItem(PENDING_KEY, JSON.stringify(map)); } catch { /* storage unavailable: backend recovers from chain */ }
}

export function BuyPayments() {
  const qc = useQueryClient();
  const payments = useQuery({queryKey: ['buy-payments'], queryFn: () => api<Payment[]>('/buy-payments'), refetchInterval: 3000, retry: false});

  // If a hash was signed but never reached the backend (tab closed, network drop), report it again.
  useEffect(() => {
    const pending = loadPending();
    Object.entries(pending).forEach(([pid, hash]) => {
      api(`/buy-payments/${pid}/submit`, {tx_hash: hash}).then(() => { delete pending[pid]; savePending(pending); }).catch(() => {});
    });
  }, []);

  const token = payments.data?.[0]?.token_address ?? USDC;
  return (
    <div className={s.page}>
      <div className={s.top}><Link href="/my-deals">← Back to Mivo</Link><span className="pill">ARC TESTNET · USDC</span></div>
      <div className="page-title"><h1>Payments<span>.</span></h1><p>BUY requests from your Raspberry Pi. Approve each one in MetaMask; it counts only after on-chain verification.</p></div>
      <div className={s.grid}>
        <WalletPanel token={token} />
        {payments.error ? (
          <div className="panel"><h2>Sign in to see payments</h2><p>Log in with the buyer account linked to your Raspberry Pi.</p><Button asChild><Link href="/login">Sign in</Link></Button></div>
        ) : payments.isLoading ? (
          <div className="panel"><p>Loading payments…</p></div>
        ) : payments.data?.length ? (
          payments.data.map(p => <PaymentCard key={p.id} p={p} onChange={() => qc.invalidateQueries({queryKey: ['buy-payments']})} />)
        ) : (
          <div className="panel"><h2>No payments yet</h2><p>Scan a product on the Pi, negotiate, then double-press to BUY. The payment request appears here.</p></div>
        )}
      </div>
    </div>
  );
}

function WalletPanel({token}: {token: Address}) {
  const {address, chainId, isConnected} = useAccount();
  const {connect, connectors, isPending, error} = useConnect();
  const {disconnect} = useDisconnect();
  const {switchChain, isPending: switching, error: switchError} = useSwitchChain();
  const client = usePublicClient({chainId: arc.id});
  const balance = useQuery({
    queryKey: ['usdc-balance', address, token], enabled: !!address && !!client, refetchInterval: 10000,
    queryFn: () => client!.readContract({address: token, abi: erc20, functionName: 'balanceOf', args: [address!]}),
  });
  const onArc = chainId === arc.id;
  return (
    <div className={`panel ${s.wallet}`}>
      <h2 style={{margin: 0}}>MetaMask</h2>
      <div className={s.row}><span>Connected wallet</span><b className={s.mono}>{isConnected ? address : 'Not connected'}</b></div>
      <div className={s.row}><span>Network</span><b>{!isConnected ? '—' : onArc ? `Arc Testnet (${arc.id})` : `Wrong network (chain ${chainId})`}</b></div>
      <div className={s.row}><span>USDC balance</span><b>{!isConnected ? '—' : balance.data !== undefined ? `${formatUnits(balance.data, 6)} USDC` : balance.isError ? 'Could not read' : '…'}</b></div>
      <div className={s.actions}>
        {!isConnected ? (
          <Button disabled={isPending || !connectors[0]} onClick={() => connect({connector: connectors[0]})}>{isPending ? 'Connecting…' : 'Connect MetaMask'}</Button>
        ) : (
          <>
            {!onArc && <Button disabled={switching} onClick={() => switchChain({chainId: arc.id})}>{switching ? 'Check MetaMask…' : 'Switch to Arc Testnet'}</Button>}
            <Button variant="ghost" onClick={() => disconnect()}>Disconnect</Button>
          </>
        )}
      </div>
      {(error || switchError) && <p className={`${s.status} ${s.warn}`} role="alert">{friendlyError(error ?? switchError)}</p>}
      <p className={s.status} style={{color: 'var(--muted)'}}>Need testnet USDC? Use the official Circle faucet at <a href="https://faucet.circle.com/" target="_blank" rel="noreferrer">faucet.circle.com</a> and choose Arc Testnet.</p>
    </div>
  );
}

function PaymentCard({p, onChange}: {p: Payment; onChange: () => void}) {
  const {address, chainId} = useAccount();
  const client = usePublicClient({chainId: arc.id});
  const {data: wallet} = useWalletClient();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [nowS, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => { const t = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000); return () => clearInterval(t); }, []);

  const final = FINAL.includes(p.status);
  const canPay = (p.status === 'pending' || p.status === 'awaiting_approval') && !p.tx_hash && p.expires > nowS;
  const left = Math.max(0, p.expires - nowS);

  async function pay() {
    if (!address) return setMessage('Connect MetaMask first.');
    if (chainId !== arc.id) return setMessage('Switch MetaMask to Arc Testnet first.');
    if (!wallet || !client) return setMessage('Wallet is not ready yet; try again in a moment.');
    setBusy(true);
    try {
      setMessage('Checking your USDC balance on Arc Testnet…');
      await api(`/buy-payments/${p.id}/start`, {payer_address: address}); // backend reads the balance on-chain
      const amount = BigInt(p.token_amount); // 6-decimal ERC-20 units, from the backend
      // transfer(recipient, amount) plus the 32-byte payment reference the backend will look for.
      const data = (encodeFunctionData({abi: erc20, functionName: 'transfer', args: [p.recipient, amount]}) + p.reference.slice(2)) as Hex;
      // Gas is paid in native USDC (18 decimals) from the same balance, so check both together.
      const [gas, price, native] = await Promise.all([
        client.estimateGas({account: address, to: p.token_address, data}), client.getGasPrice(), client.getBalance({address}),
      ]);
      const fee = (gas * 12n / 10n) * price;
      if (native < amount * 10n ** 12n + fee) {
        await api(`/buy-payments/${p.id}/report`, {kind: 'insufficient_gas', detail: `need ~${formatUnits(fee, 18)} USDC for gas on top of the payment`});
        setMessage('Not enough USDC to cover the payment plus gas.');
        return;
      }
      setMessage('Approve the payment in MetaMask…');
      let hash: Hex;
      try {
        hash = await wallet.sendTransaction({account: address, chain: arc, to: p.token_address, data, gas: gas * 12n / 10n});
      } catch (e) {
        if (isRejection(e)) {
          await api(`/buy-payments/${p.id}/report`, {kind: 'rejected'});
          setMessage('You rejected the payment in MetaMask. Nothing was sent.');
          return;
        }
        throw e;
      }
      const pending = loadPending(); pending[p.id] = hash; savePending(pending);
      setMessage('Submitted. The server is verifying it on Arc Testnet…');
      await api(`/buy-payments/${p.id}/submit`, {tx_hash: hash});
      delete pending[p.id]; savePending(pending);
    } catch (e) {
      setMessage(friendlyError(e));
    } finally {
      setBusy(false);
      onChange();
    }
  }

  const pillClass = p.status === 'paid' ? 'pill green' : final ? `pill ${s.pillBad}` : `pill ${s.pillWarn}`;
  return (
    <article className="panel">
      <div className={s.head}>
        <div><h2>{p.product}</h2><p>{p.dealer} · requested {time(p.created)} · {p.id}</p></div>
        <div className={s.amount}>{p.amount_usdc} USDC</div>
      </div>
      <span className={pillClass}>{busy && !final ? 'Waiting for MetaMask approval' : p.label}</span>

      {p.status === 'paid' && <div className={s.success} role="status">PAYMENT SUCCESSFUL</div>}
      {final && p.status !== 'paid' && <div className={s.failed} role="alert"><b>PAYMENT FAILED</b>{p.reason}</div>}

      <div style={{marginTop: 12}}>
        <div className={s.row}><span>Product</span><b>{p.product}</b></div>
        <div className={s.row}><span>Amount</span><b>{p.amount_usdc} USDC</b></div>
        <div className={s.row}><span>Paying wallet</span><b className={s.mono}>{p.payer ?? address ?? 'Connect MetaMask'}</b></div>
        <div className={s.row}><span>Recipient (merchant)</span><b className={s.mono}>{p.recipient}</b></div>
        <div className={s.row}><span>Status</span><b>{p.label}{p.block_number ? ` · block ${p.block_number}` : ''}</b></div>
        <div className={s.row}><span>Transaction hash</span><b className={s.mono}>{p.tx_hash ?? '—'}</b></div>
        <div className={s.row}><span>Explorer</span><b>{p.explorer_url ? <a href={p.explorer_url} target="_blank" rel="noreferrer">View on Arc Testnet Explorer ↗</a> : '—'}</b></div>
      </div>

      {canPay && (
        <div className={s.actions}>
          <Button disabled={busy} onClick={pay}>{busy ? 'Processing…' : `Approve ${p.amount_usdc} USDC in MetaMask`}</Button>
          <span style={{fontSize: 12, color: 'var(--muted)'}}>Approve within {Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')}</span>
        </div>
      )}
      {message && <p className={s.status} role="status">{message}</p>}

      <ol className={s.steps}>
        {p.events.map((e, i) => <li key={i}><time>{time(e.at)}</time><b>{e.label}</b>{e.note && <span className={s.mono}>{e.note.length > 70 ? short(e.note) : e.note}</span>}</li>)}
      </ol>
    </article>
  );
}
