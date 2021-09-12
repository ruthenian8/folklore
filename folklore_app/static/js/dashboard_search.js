function updateOptions(names, to_id, data, mode) {
    console.log(names);
    var topicSel = document.getElementById(to_id);
    topicSel.length = 1;
    if (mode === 1){
        names.forEach(
            (name) => {
                let z = data[name];
                console.log("mode 1", z);
                for (var i = 0; i < z.length; i++) {
                    topicSel.options[topicSel.options.length] = new Option(z[i], z[i]);
                }
            }
        )
    } else {
        names.forEach(
            (name) => {
                console.log("mode 2", data[name]);
                for (var y in data[name]) {
                    topicSel.options[topicSel.options.length] = new Option(y, y);
                }
            }
        )
    }
}

function simpleDistrict(data) {
    const selected = document.querySelectorAll('#region option:checked');
    const values = Array.from(selected).map(el => el.value);
    console.log("simpleDistrict", values);
    updateOptions(values, "district", data, mode=2)
}

function simpleVillage(data) {
    const selected = document.querySelectorAll('#district option:checked');
    const values = Array.from(selected).map(el => el.value);
    console.log("simpleVillage", values);
    updateOptions(values, "village", data, mode=1)
}