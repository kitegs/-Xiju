import { use } from 'echarts/core'
import {
  BarChart, BoxplotChart, GaugeChart, HeatmapChart, LineChart, PieChart,
  RadarChart, ScatterChart, TreemapChart,
} from 'echarts/charts'
import {
  DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent,
  TitleComponent, ToolboxComponent, TooltipComponent, VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([
  BarChart, BoxplotChart, GaugeChart, HeatmapChart, LineChart, PieChart,
  RadarChart, ScatterChart, TreemapChart,
  DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent,
  TitleComponent, ToolboxComponent, TooltipComponent, VisualMapComponent,
  CanvasRenderer,
])

export { default as VChart } from 'vue-echarts'
