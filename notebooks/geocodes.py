import pandas as pd

df = pd.read_csv('geocodes.csv', sep='\t')

pattern = """
<table>
    <tr>
        <td>Область</td>
        <td>Х</td>
    </tr>
    <tr>
        <td>Район</td>
        <td>Х</td>
    </tr>
    <tr>
        <td>Населенный пункт</td>
        <td>{}</td>
    </tr>
    <tr>
        <td>Год</td>
        <td>{}</td>
    </tr>
    <tr>
        <td><a href='http://wikipedia.org'>Искать в корпусе</a></td>
    </tr>
    <tr>
        <td><img src='https://github.com/dkbrz/folklore/blob/dev/folklore_app/static/img/search_in_progress.gif?raw=true'></td>
    </tr>
</table>
"""

df['Номер'] = list(range(len(df)))
df['Год обследования'] = df['Год обследования'].apply(lambda x: ';'.join([i for i in str(x).split('.') if i != '0']))
df = df[['Широта', 'Долгота', 'Год обследования', 'Название населенного пункта', 'Номер']]
data = []
for i in range(df.shape[0]):
    row = df.iloc[i]
    data.append(pattern.format(
        row['Название населенного пункта'],
        row['Год обследования']
    ))
df['Год обследования'] = data
# print(df)
df.to_csv('changed.csv', sep='\t', index=False)
