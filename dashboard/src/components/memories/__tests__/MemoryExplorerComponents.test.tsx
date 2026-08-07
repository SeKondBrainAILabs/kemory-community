import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MarkdownView } from '@/components/shared/MarkdownView'
import { Pagination, getPageList } from '@/components/shared/Pagination'
import { NamespaceCombobox } from '@/components/memories/NamespaceCombobox'

describe('MarkdownView', () => {
  it('renders useful markdown without enabling unsafe links', () => {
    render(
      <MarkdownView content={'## Notes\n\n**Important** and [docs](https://example.com) or [bad](javascript:alert(1))'} />,
    )

    expect(screen.getByText('Notes')).toBeInTheDocument()
    expect(screen.getByText('Important').tagName).toBe('STRONG')
    expect(screen.getByRole('link', { name: 'docs' })).toHaveAttribute('href', 'https://example.com')
    expect(screen.queryByRole('link', { name: 'bad' })).not.toBeInTheDocument()
  })
})

describe('Pagination', () => {
  it('builds a bounded page list and emits page changes', async () => {
    expect(getPageList(6, 20)).toEqual([1, 'gap', 5, 6, 7, 'gap', 20])
    const onPageChange = vi.fn()
    const user = userEvent.setup()

    render(
      <Pagination
        page={5}
        pageCount={20}
        pageSize={50}
        total={987}
        onPageChange={onPageChange}
        onPageSizeChange={vi.fn()}
      />,
    )

    expect(screen.getByLabelText('Page 6')).toHaveAttribute('aria-current', 'page')
    await user.click(screen.getByLabelText('Next page'))
    expect(onPageChange).toHaveBeenCalledWith(6)
  })
})

describe('NamespaceCombobox', () => {
  it('filters namespaces and returns the selected value', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(
      <NamespaceCombobox
        namespaces={[
          { namespace: 'project:alpha', count: 4 },
          { namespace: 'project:beta', count: 2 },
        ]}
        value=""
        totalCount={6}
        onChange={onChange}
      />,
    )

    await user.click(screen.getByRole('combobox'))
    await user.type(screen.getByLabelText('Search namespaces'), 'beta')
    expect(screen.queryByText('project:alpha')).not.toBeInTheDocument()
    await user.click(screen.getByText('project:beta'))
    expect(onChange).toHaveBeenCalledWith('project:beta')
  })
})
