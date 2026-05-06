/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

function toMany2oneId(value) {
    if (!value) {
        return false;
    }
    if (Array.isArray(value)) {
        return value[0];
    }
    if (typeof value === "number") {
        return value;
    }
    return false;
}

function toMany2manyIds(value) {
    if (!value) {
        return [];
    }
    if (Array.isArray(value)) {
        if (value.length === 0 || typeof value[0] === "number") {
            return value.filter((id) => typeof id === "number");
        }
        if (Array.isArray(value[0]) && value[0][0] === 6 && Array.isArray(value[0][2])) {
            return value[0][2];
        }
        return [];
    }
    if (value.records && Array.isArray(value.records)) {
        return value.records.map((r) => r.resId).filter((id) => typeof id === "number");
    }
    return [];
}

class EstateGenerateDescriptionButton extends Component {
    static template = "estate.GenerateDescriptionButton";

    async onClick() {
        const record = this.props.record;
        if (!record) {
            this.env.services.notification.add(_t("No active record found."), { type: "warning" });
            return;
        }
        const data = record.data || {};
        const payload = {
            name: data.name,
            expected_price: data.expected_price,
            bedrooms: data.bedrooms,
            living_area: data.living_area,
            garden_area: data.garden_area,
            total_area: data.total_area,
            property_type_id: toMany2oneId(data.property_type_id),
            tag_ids: toMany2manyIds(data.tag_ids),
            style: data.ai_description_tone || "luxury",
            language: data.ai_description_language || "en",
            rules: data.ai_description_rules || "",
        };

        let result;
        try {
            result = await this.env.services.orm.call("estate.ai.service", "preview_property_description", [payload]);
        } catch (error) {
            const message = error?.data?.message || error?.message || _t("Failed to generate description.");
            this.env.services.notification.add(message, { type: "danger" });
            return;
        }

        if (result?.description) {
            record.update({ description: result.description });
            const provider = result.provider || _t("AI");
            this.env.services.notification.add(_t("Description generated (%s).").replace("%s", provider), { type: "success" });
        }
    }
}

registry.category("fields").add("estate_generate_description_button", {
    component: EstateGenerateDescriptionButton,
    supportedTypes: ["boolean", "integer"],
});
