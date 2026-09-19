<script setup>
import { onMounted, watch, ref } from 'vue'
import * as echarts from 'echarts'
const props = defineProps({ option: Object, height: { type: String, default: '280px' } })
const el = ref(null)
let chart = null
onMounted(() => {
  chart = echarts.init(el.value)
  if (props.option) chart.setOption(props.option)
  window.addEventListener('resize', () => chart && chart.resize())
})
watch(() => props.option, (v) => v && chart && chart.setOption(v, true))
</script>
<template><div ref="el" :style="{ height, width: '100%' }"></div></template>
