import { useEffect, useState } from 'react'
import { Check, Copy, ExternalLink } from 'lucide-react'
import { copyToClipboard } from '../lib/clipboard'
import { shortenAddress } from '../lib/format'

interface CopyAddressProps {
  address: string
  href?: string | null
}

export function CopyAddress({ address, href }: CopyAddressProps) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const id = window.setTimeout(() => setCopied(false), 1500)
    return () => window.clearTimeout(id)
  }, [copied])

  const iconBtn =
    'rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-indigo-500'

  return (
    <span className="inline-flex items-center gap-0.5 font-mono text-xs text-zinc-400">
      <span title={address}>{shortenAddress(address)}</span>
      <button
        type="button"
        className={iconBtn}
        aria-label={copied ? 'Address copied' : 'Copy address'}
        title={copied ? 'Copied!' : 'Copy address'}
        onClick={async () => setCopied(await copyToClipboard(address))}
      >
        {copied ? (
          <Check className="size-3.5 text-emerald-400" aria-hidden />
        ) : (
          <Copy className="size-3.5" aria-hidden />
        )}
      </button>
      {href && (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className={iconBtn}
          aria-label="Open profile"
          title="Open profile"
        >
          <ExternalLink className="size-3.5" aria-hidden />
        </a>
      )}
    </span>
  )
}
