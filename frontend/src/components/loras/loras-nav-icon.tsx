'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Sparkles as SparklesIcon } from 'lucide-react'

/**
 * "LoRAs" nav entry — opens the dedicated LoRA management page
 * (sgs-ui-eqc.3).
 */
export function LorasNavIcon() {
  const pathname = usePathname()
  const active = pathname === '/loras' || pathname?.startsWith('/loras/')
  return (
    <Link
      href="/loras"
      title="Manage LoRAs on the ComfyGen endpoint"
      aria-current={active ? 'page' : undefined}
      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs transition-all ${
        active
          ? 'bg-primary text-primary-foreground shadow-sm'
          : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
      }`}
    >
      <SparklesIcon className="w-3.5 h-3.5" />
      <span>LoRAs</span>
    </Link>
  )
}
