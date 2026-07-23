// Tree-shaken ECharts: register only the chart types + components we use,
// so the bundle is a fraction of the full ~1MB build. Import from here
// instead of "echarts".
import { use, init, graphic } from "echarts/core";
import { BarChart, PieChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsType } from "echarts/core";
import type { EChartsOption } from "echarts";

use([
  BarChart,
  PieChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  CanvasRenderer,
]);

export { init, graphic };
export type { EChartsType, EChartsOption };
