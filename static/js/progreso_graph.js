/**
 * ========================================
 * PROGRESO GRAPHS - Versión con validaciones mejoradas
 * ========================================
 */

(function() {
    'use strict';

    // Verificar que ApexCharts está disponible
    function waitForApexCharts(callback, maxAttempts = 10) {
        let attempts = 0;
        const interval = setInterval(() => {
            attempts++;
            if (typeof ApexCharts !== 'undefined') {
                clearInterval(interval);
                console.log('✅ ApexCharts cargado correctamente');
                callback();
            } else if (attempts >= maxAttempts) {
                clearInterval(interval);
                console.error('❌ ApexCharts no se cargó después de', maxAttempts, 'intentos');
                showErrorMessage('No se pudo cargar la librería de gráficos');
            }
        }, 100);
    }

    function showErrorMessage(message) {
        const containers = ['forestPlotChart', 'categoriasChart', 'estadosChart'];
        containers.forEach(id => {
            const container = document.getElementById(id);
            if (container) {
                container.innerHTML = `
                    <div class="flex flex-col items-center justify-center py-16">
                        <svg class="w-16 h-16 text-red-300 dark:text-red-600 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                        </svg>
                        <p class="text-red-500 dark:text-red-400 font-medium">${message}</p>
                    </div>
                `;
            }
        });
    }

    // Inicializar cuando el DOM esté listo
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => waitForApexCharts(init));
    } else {
        waitForApexCharts(init);
    }

    function init() {
        console.log('🚀 Inicializando Dashboard de Progreso...');

        // Obtener y validar datos
        const chartDataElement = document.getElementById('chart-data');
        if (!chartDataElement) {
            console.error('❌ Elemento chart-data no encontrado');
            showErrorMessage('No se encontraron datos para los gráficos');
            return;
        }

        let chartData;
        try {
            const rawData = chartDataElement.textContent.trim();
            console.log('📄 Datos raw length:', rawData.length);
            chartData = JSON.parse(rawData);
            console.log('✅ Datos parseados:', chartData);
        } catch (e) {
            console.error('❌ Error al parsear datos:', e);
            console.log('📄 Contenido problemático:', chartDataElement.textContent.substring(0, 200));
            showErrorMessage('Error al cargar los datos del gráfico');
            return;
        }

        // Validar estructura de datos
        if (!chartData.forestPlot || !chartData.resumen) {
            console.error('❌ Estructura de datos inválida:', chartData);
            showErrorMessage('Datos incompletos');
            return;
        }

        // Detectar tema
        const isDark = document.documentElement.classList.contains('dark');
        console.log('🎨 Tema detectado:', isDark ? 'Oscuro' : 'Claro');

        const colors = {
            text: isDark ? '#D1D5DB' : '#374151',
            grid: isDark ? '#374151' : '#E5E7EB',
            background: isDark ? '#1F2937' : '#FFFFFF',
            completado: '#10B981',
            aprobado: '#3B82F6',
            pendiente: '#EF4444'
        };

        // Inicializar gráficos
        if (chartData.hasForestPlot && chartData.forestPlot.articulos.length > 0) {
            console.log('📊 Inicializando Forest Plot con', chartData.forestPlot.articulos.length, 'artículos');
            initForestPlot(chartData.forestPlot, colors, isDark);
        } else {
            console.warn('⚠️ No hay datos para Forest Plot');
        }

        if (chartData.hasCategorias && chartData.categorias.labels.length > 0) {
            console.log('📊 Inicializando Gráfico de Categorías');
            initCategoriasChart(chartData.categorias, colors, isDark);
        } else {
            console.warn('⚠️ No hay datos para Categorías');
        }

        if (chartData.resumen && chartData.resumen.data.length > 0) {
            console.log('📊 Inicializando Gráfico de Estados');
            initEstadosChart(chartData.resumen, colors, isDark);
        } else {
            console.warn('⚠️ No hay datos para Estados');
        }

        setupResponsive(chartData);
        console.log('✅ Dashboard cargado correctamente');
    }

    // ... (el resto de las funciones permanecen igual)
    // initForestPlot, initCategoriasChart, initEstadosChart, setupResponsive

    function initForestPlot(data, colors, isDark) {
        const container = document.getElementById('forestPlotChart');
        if (!container) {
            console.warn('⚠️ Contenedor forestPlotChart no encontrado');
            return;
        }

        const options = {
            series: [
                { name: 'Completados', data: data.completados },
                { name: 'Aprobados', data: data.aprobados },
                { name: 'Pendientes', data: data.pendientes }
            ],
            chart: {
                type: 'bar',
                height: 600,
                stacked: true,
                background: colors.background,
                toolbar: {
                    show: true,
                    tools: {
                        download: true,
                        selection: false,
                        zoom: false,
                        zoomin: false,
                        zoomout: false,
                        pan: false,
                        reset: false
                    }
                },
                fontFamily: 'Inter, system-ui, sans-serif',
                animations: {
                    enabled: true,
                    easing: 'easeinout',
                    speed: 800
                }
            },
            plotOptions: {
                bar: {
                    horizontal: true,
                    barHeight: '70%',
                    dataLabels: { position: 'center' }
                }
            },
            colors: [colors.completado, colors.aprobado, colors.pendiente],
            dataLabels: {
                enabled: true,
                style: { colors: ['#fff'], fontSize: '11px', fontWeight: 600 },
                formatter: (val) => val > 0 ? val : ''
            },
            xaxis: {
                categories: data.articulos,
                labels: {
                    style: { colors: colors.text, fontSize: '12px' }
                },
                axisBorder: { color: colors.grid },
                title: {
                    text: 'Número de Campos',
                    style: { color: colors.text, fontSize: '13px', fontWeight: 600 }
                }
            },
            yaxis: {
                labels: {
                    style: { colors: colors.text, fontSize: '11px' },
                    maxWidth: 180
                }
            },
            grid: {
                borderColor: colors.grid,
                strokeDashArray: 4,
                xaxis: { lines: { show: true } },
                yaxis: { lines: { show: false } }
            },
            legend: {
                position: 'top',
                horizontalAlign: 'center',
                labels: { colors: colors.text },
                markers: { width: 12, height: 12, radius: 3 },
                itemMargin: { horizontal: 15, vertical: 5 }
            },
            tooltip: {
                theme: isDark ? 'dark' : 'light',
                shared: true,
                intersect: false,
                y: {
                    formatter: (val, { dataPointIndex }) => {
                        const total = data.totalCampos[dataPointIndex];
                        const percent = total > 0 ? ((val / total) * 100).toFixed(1) : 0;
                        return `${val} campos (${percent}%)`;
                    }
                }
            }
        };

        try {
            window.forestPlotChart = new ApexCharts(container, options);
            window.forestPlotChart.render();
            console.log('✅ Forest Plot renderizado');
        } catch (e) {
            console.error('❌ Error al renderizar Forest Plot:', e);
            showErrorMessage('Error al renderizar gráfico principal');
        }
    }

    function initCategoriasChart(data, colors, isDark) {
        const container = document.getElementById('categoriasChart');
        if (!container) return;

        const options = {
            series: [
                { name: 'Completados', data: data.completados },
                { name: 'Aprobados', data: data.aprobados },
                { name: 'Pendientes', data: data.pendientes }
            ],
            chart: {
                type: 'bar',
                height: 300,
                stacked: true,
                background: colors.background,
                toolbar: { show: false },
                fontFamily: 'Inter, system-ui, sans-serif'
            },
            plotOptions: {
                bar: { horizontal: false, borderRadius: 6, columnWidth: '60%' }
            },
            colors: [colors.completado, colors.aprobado, colors.pendiente],
            xaxis: {
                categories: data.labels,
                labels: {
                    style: { colors: colors.text, fontSize: '11px' },
                    rotate: -45
                }
            },
            yaxis: {
                labels: { style: { colors: colors.text } }
            },
            grid: { borderColor: colors.grid },
            legend: {
                position: 'bottom',
                labels: { colors: colors.text }
            }
        };

        try {
            window.categoriasChart = new ApexCharts(container, options);
            window.categoriasChart.render();
            console.log('✅ Gráfico de Categorías renderizado');
        } catch (e) {
            console.error('❌ Error al renderizar Categorías:', e);
        }
    }

    function initEstadosChart(data, colors, isDark) {
        const container = document.getElementById('estadosChart');
        if (!container) return;

        const options = {
            series: data.data,
            chart: {
                type: 'donut',
                height: 300,
                background: colors.background,
                fontFamily: 'Inter, system-ui, sans-serif'
            },
            labels: data.labels,
            colors: ['#F59E0B', '#3B82F6', '#8B5CF6', '#10B981', '#6366F1'],
            legend: {
                position: 'bottom',
                labels: { colors: colors.text }
            },
            plotOptions: {
                pie: {
                    donut: {
                        size: '65%',
                        labels: {
                            show: true,
                            total: {
                                show: true,
                                label: 'Total',
                                color: colors.text
                            }
                        }
                    }
                }
            }
        };

        try {
            window.estadosChart = new ApexCharts(container, options);
            window.estadosChart.render();
            console.log('✅ Gráfico de Estados renderizado');
        } catch (e) {
            console.error('❌ Error al renderizar Estados:', e);
        }
    }

    function setupResponsive(chartData) {
        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                if (chartData.hasForestPlot && window.forestPlotChart) {
                    const newHeight = window.innerWidth < 768 ? 800 : 600;
                    window.forestPlotChart.updateOptions({ chart: { height: newHeight } });
                }
            }, 250);
        });
    }

})();