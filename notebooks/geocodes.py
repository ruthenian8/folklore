import pandas as pd
import mysql.connector
db = mysql.connector.connect(user='root', password='password', database='folklore_db2', charset='utf8mb4')
cur = db.cursor()
df = pd.read_sql_query("""
    SELECT 
        id,
        map_region as region,
        map_district as district,
        village_name as village,
        map_lat as lat,
        map_lon as lon,
        years,
        map_image
    FROM g_villages
    WHERE map_lat IS NOT NULL 
    """, con=db)

pattern = """
<table>
    <tr>
        <td>Область</td>
        <td>{}</td>
    </tr>
    <tr>
        <td>Район</td>
        <td>{}</td>
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
        <td><a target="_blank" href='https://linghub.ru/folklore/results?&submit=Поиск&village={}'>Искать в корпусе</a></td>
    </tr>
    <tr>
        <td colspan=2><img src='https://raw.githubusercontent.com/dkbrz/folklore_images/master/map_images/{}'></td>
    </tr>
</table>
"""

# df['Номер'] = list(range(len(df)))
# df['Год обследования'] = df['Год обследования'].apply(lambda x: ';'.join([i for i in str(x).split('.') if i != '0']))
# df = df[['Широта', 'Долгота', 'Год обследования', 'Название населенного пункта', 'Номер']]
# data = []
# for i in range(df.shape[0]):
#     row = df.iloc[i]
#     data.append(pattern.format(
#         row['Название населенного пункта'],
#         row['Год обследования']
#     ))
# df['Год обследования'] = data
# # print(df)
data = []
for i in range(df.shape[0]):
    row = df.iloc[i]
    data.append((
        row['lat'],
        row['lon'],
        pattern.format(
            row['region'],
            row['district'],
            row['village'],
            row['years'],
            row['village'],
            row['map_image']
        ),
        row['village'],
        row['id']
    ))
data = pd.DataFrame(data)
data.columns = ['Широта', 'Долгота', 'Год обследования', 'Название населенного пункта', 'Номер']
data.to_csv('changed2.csv', sep='\t', index=False)
