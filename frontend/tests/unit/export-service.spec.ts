import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('html2canvas', () => ({
  default: vi.fn(async () => ({
    width: 1000,
    height: 2000,
    toDataURL: vi.fn(() => 'data:image/png;base64,abc'),
  })),
}))

const addImage = vi.fn()
const addPage = vi.fn()
const save = vi.fn()
vi.mock('jspdf', () => ({
  default: function MockJsPDF(this: any) {
    this.addImage = addImage
    this.addPage = addPage
    this.save = save
  },
}))

describe('export-service', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div class="main-content"><div id="mapbox-container"></div></div>'
    addImage.mockReset()
    addPage.mockReset()
    save.mockReset()
  })

  it('导出图片时会触发下载链接', async () => {
    const click = vi.fn()
    const originalCreateElement = document.createElement.bind(document)
    const createElement = vi.spyOn(document, 'createElement')
    createElement.mockImplementation(((tagName: string) => {
      const el = originalCreateElement(tagName) as any
      if (tagName === 'a') el.click = click
      return el
    }) as any)
    const { exportAsImageFile } = await import('@/services/export-service')
    await exportAsImageFile({ city: 'Paris', mainContentSelector: '.main-content' })
    expect(click).toHaveBeenCalled()
    createElement.mockRestore()
  })

  it('导出 PDF 时会调用 save', async () => {
    const { exportAsPdfFile } = await import('@/services/export-service')
    await exportAsPdfFile({ city: 'Paris', mainContentSelector: '.main-content' })
    expect(save).toHaveBeenCalled()
  })
})

