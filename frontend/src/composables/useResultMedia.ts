import { message } from "ant-design-vue";
import type { Ref } from "vue";
import type { TripPlan } from "@/types";
import { exportAsImageFile, exportAsPdfFile } from "@/services/export-service";

export function useResultMedia(
  tripPlan: Ref<TripPlan | null>,
  getMapSnapshotDataUrl: () => string | null,
) {
  const loadAttractionPhotos = async (
    getTripDays: () => any[],
    attractionPhotos: Ref<Record<string, string>>,
  ) => {
    if (!tripPlan.value) return;

    const promises: Promise<void>[] = [];

    getTripDays().forEach((day: any) => {
      (day.attractions || []).forEach((attraction: any) => {
        if (attraction.image_url) {
          attractionPhotos.value[attraction.name] = attraction.image_url;
          return;
        }

        const refs = attraction.photo_references || [];
        if (refs.length > 0) {
          attractionPhotos.value[attraction.name] = refs[0];
          return;
        }

        const apiBase =
          (import.meta as any).env?.VITE_API_BASE_URL ||
          "http://localhost:8881";
        const promise = fetch(
          `${apiBase}/api/poi/photo?name=${encodeURIComponent(attraction.name)}`,
        )
          .then((res) => res.json())
          .then((data) => {
            if (data.success && data.data.photo_url) {
              attractionPhotos.value[attraction.name] = data.data.photo_url;
            }
          })
          .catch((err) => {
            console.error(`获取${attraction.name}图片失败:`, err);
          });

        promises.push(promise);
      });
    });

    await Promise.all(promises);
  };

  const getAttractionImage = (
    attractionPhotos: Ref<Record<string, string>>,
    attraction: any,
    index: number,
  ): string => {
    const name = attraction?.name || `景点${index + 1}`;
    if (attractionPhotos.value[name]) {
      return attractionPhotos.value[name];
    }

    const colors = [
      { start: "#667eea", end: "#764ba2" },
      { start: "#f093fb", end: "#f5576c" },
      { start: "#4facfe", end: "#00f2fe" },
      { start: "#43e97b", end: "#38f9d7" },
      { start: "#fa709a", end: "#fee140" },
    ];
    const colorIndex = index % colors.length;
    const { start, end } = colors[colorIndex];

    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">
      <defs>
        <linearGradient id="grad${index}" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:${start};stop-opacity:1" />
          <stop offset="100%" style="stop-color:${end};stop-opacity:1" />
        </linearGradient>
      </defs>
      <rect width="400" height="300" fill="url(#grad${index})"/>
      <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="24" font-weight="bold" fill="white">${name}</text>
    </svg>`;

    return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`;
  };

  const handleImageError = (event: Event) => {
    const img = event.target as HTMLImageElement;
    img.src =
      'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="400" height="300"%3E%3Crect width="400" height="300" fill="%23f0f0f0"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="18" fill="%23999"%3E图片加载失败%3C/text%3E%3C/svg%3E';
  };

  const exportAsImage = async () => {
    try {
      message.loading({
        content: "正在生成图片...",
        key: "export",
        duration: 0,
      });
      await exportAsImageFile({
        city: tripPlan.value?.city,
        mapSnapshot: getMapSnapshotDataUrl(),
        mainContentSelector: ".main-content",
      });
      message.success({ content: "图片导出成功!", key: "export" });
    } catch (error: any) {
      console.error("导出图片失败:", error);
      message.error({
        content: `导出图片失败: ${error.message}`,
        key: "export",
      });
    }
  };

  const exportAsPDF = async () => {
    try {
      message.loading({
        content: "正在生成PDF...",
        key: "export",
        duration: 0,
      });
      await exportAsPdfFile({
        city: tripPlan.value?.city,
        mapSnapshot: getMapSnapshotDataUrl(),
        mainContentSelector: ".main-content",
      });
      message.success({ content: "PDF导出成功!", key: "export" });
    } catch (error: any) {
      console.error("导出PDF失败:", error);
      message.error({
        content: `导出PDF失败: ${error.message}`,
        key: "export",
      });
    }
  };

  return {
    loadAttractionPhotos,
    getAttractionImage,
    handleImageError,
    exportAsImage,
    exportAsPDF,
  };
}
