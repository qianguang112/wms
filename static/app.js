// 自动计算固定资产总价值
document.addEventListener('DOMContentLoaded', () => {
    const qtyEl = document.querySelector('[name="qty"]');
    const priceEl = document.querySelector('[name="unit_price"]');
    const totalEl = document.querySelector('[name="total_value"]');
    if (qtyEl && priceEl && totalEl) {
        const calc = () => {
            const qty = parseFloat(qtyEl.value) || 0;
            const price = parseFloat(priceEl.value) || 0;
            totalEl.value = (qty * price).toFixed(2);
        };
        qtyEl.addEventListener('input', calc);
        priceEl.addEventListener('input', calc);
    }

    // 办公用品 - 入库/领用快捷入口跳转
    const supplySelect = document.querySelector('[data-supply-select]');
    if (supplySelect) {
        const inboundBtn = document.querySelector('[data-inbound-btn]');
        const outboundBtn = document.querySelector('[data-outbound-btn]');
        if (inboundBtn) {
            inboundBtn.addEventListener('click', () => {
                const id = supplySelect.value;
                if (id) window.location.href = `/supplies/${id}/inbound`;
            });
        }
        if (outboundBtn) {
            outboundBtn.addEventListener('click', () => {
                const id = supplySelect.value;
                if (id) window.location.href = `/supplies/${id}/outbound`;
            });
        }
    }

    // 资产报废确认
    document.querySelectorAll('[data-scrap-btn]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            if (!confirm('确定要报废该资产吗？此操作不可撤销。')) {
                e.preventDefault();
            }
        });
    });

    // 删除确认
    document.querySelectorAll('[data-delete-btn]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            if (!confirm('确定要删除吗？此操作不可撤销。')) {
                e.preventDefault();
            }
        });
    });
});
