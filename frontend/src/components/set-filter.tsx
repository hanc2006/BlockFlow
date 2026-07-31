'use client'

import { useMemo, useState } from 'react'
import { Check, Layers, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { MediaSet } from '@/lib/api'

interface SetFilterProps {
  sets: MediaSet[]
  selectedId: string | null
  onChange: (id: string | null) => void
}

/** Picks the Set the Artifacts grid is filtered to. The list is type-to-narrow
 * because sets accumulate, and each row carries its item count. */
export function SetFilter({ sets, selectedId, onChange }: SetFilterProps) {
  const [query, setQuery] = useState('')
  const needle = query.trim().toLowerCase()

  const shown = useMemo(
    () => (needle ? sets.filter((s) => s.name.toLowerCase().includes(needle)) : sets),
    [needle, sets],
  )
  const selected = sets.find((s) => s.id === selectedId)

  const pick = (id: string | null) => {
    setQuery('')
    onChange(id)
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant={selected ? 'default' : 'outline'}
          size="sm"
          className={`h-8 px-3 text-xs gap-1.5 ${selected ? 'bg-violet-500/20 text-violet-300 border border-violet-500/30 hover:bg-violet-500/30' : ''}`}
        >
          <Layers className="size-3.5" />
          {selected ? selected.name : 'Set'}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64 max-h-80 overflow-y-auto p-1.5">
        {sets.length === 0 ? (
          <p className="px-2 py-3 text-xs text-muted-foreground">
            No sets yet. Ask Claude to create one via the BlockFlow MCP.
          </p>
        ) : (
          <>
            <div className="relative mb-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.stopPropagation()}
                placeholder="Search sets..."
                className="h-8 pl-8 text-xs"
              />
            </div>
            <DropdownMenuItem onSelect={() => pick(null)} className="text-xs">
              All sets
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {shown.length === 0 ? (
              <p className="px-2 py-3 text-xs text-muted-foreground">No sets match that name.</p>
            ) : (
              shown.map((s) => (
                <DropdownMenuItem
                  key={s.id}
                  onSelect={() => pick(s.id)}
                  className="text-xs flex items-center gap-2"
                >
                  {s.id === selectedId ? (
                    <Check className="size-3.5 shrink-0" />
                  ) : (
                    <span className="size-3.5 shrink-0" />
                  )}
                  <span className="truncate">{s.name}</span>
                  <span className="ml-auto text-muted-foreground">{s.item_count}</span>
                </DropdownMenuItem>
              ))
            )}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
