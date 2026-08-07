import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect } from 'vitest'
import { Sidebar } from '../Sidebar'

function renderSidebar() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Sidebar', () => {
  it('shows the community workspaces', () => {
    renderSidebar()

    expect(screen.getByText('Overview')).toBeInTheDocument()
    const expectedItems = [
      'Memories',
      'Chats',
      'Namespaces',
      'Artifacts',
      'Doctor',
      'Chat Mappings',
      'Settings',
    ]

    for (const item of expectedItems) {
      expect(screen.getByText(item)).toBeInTheDocument()
    }
  })
})
