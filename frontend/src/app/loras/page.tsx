import { Suspense } from 'react'

import { LorasPageBody } from '@/components/loras/loras-page-body'

export default function LorasPage() {
  return (
    <Suspense fallback={null}>
      <LorasPageBody />
    </Suspense>
  )
}
