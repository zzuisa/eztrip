import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'

function buildExportContainer(element: HTMLElement, mapSnapshot?: string | null): HTMLElement {
  const exportContainer = document.createElement('div')
  exportContainer.style.width = `${element.offsetWidth}px`
  exportContainer.style.backgroundColor = '#f5f7fa'
  exportContainer.style.padding = '20px'
  exportContainer.innerHTML = element.innerHTML
  if (mapSnapshot) {
    const exportMapContainer = exportContainer.querySelector('#mapbox-container')
    if (exportMapContainer) {
      exportMapContainer.innerHTML = `<img src="${mapSnapshot}" style="width:100%;height:100%;object-fit:cover;" />`
    }
  }
  exportContainer.style.position = 'absolute'
  exportContainer.style.left = '-9999px'
  return exportContainer
}

async function snapshotMainContent(mainContentSelector: string, mapSnapshot?: string | null) {
  const element = document.querySelector(mainContentSelector) as HTMLElement | null
  if (!element) throw new Error('未找到内容元素')
  const exportContainer = buildExportContainer(element, mapSnapshot)
  document.body.appendChild(exportContainer)
  const canvas = await html2canvas(exportContainer, {
    backgroundColor: '#f5f7fa',
    scale: 2,
    logging: false,
    useCORS: true,
    allowTaint: true,
  })
  document.body.removeChild(exportContainer)
  return canvas
}

export async function exportAsImageFile(params: {
  city?: string
  mapSnapshot?: string | null
  mainContentSelector?: string
}) {
  const canvas = await snapshotMainContent(params.mainContentSelector || '.main-content', params.mapSnapshot)
  const link = document.createElement('a')
  link.download = `旅行计划_${params.city || 'unknown'}_${Date.now()}.png`
  link.href = canvas.toDataURL('image/png')
  link.click()
}

export async function exportAsPdfFile(params: {
  city?: string
  mapSnapshot?: string | null
  mainContentSelector?: string
}) {
  const canvas = await snapshotMainContent(params.mainContentSelector || '.main-content', params.mapSnapshot)
  const imgData = canvas.toDataURL('image/png')
  const pdf = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
  const imgWidth = 210
  const imgHeight = (canvas.height * imgWidth) / canvas.width
  let heightLeft = imgHeight
  let position = 0
  pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight)
  heightLeft -= 297
  while (heightLeft > 0) {
    position = heightLeft - imgHeight
    pdf.addPage()
    pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight)
    heightLeft -= 297
  }
  pdf.save(`旅行计划_${params.city || 'unknown'}_${Date.now()}.pdf`)
}

