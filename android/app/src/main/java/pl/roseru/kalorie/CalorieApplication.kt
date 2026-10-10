package pl.roseru.kalorie

import android.app.Application
import androidx.room.Room
import pl.roseru.kalorie.data.*

class CalorieApplication : Application() {
    val database by lazy { Room.databaseBuilder(this, CalorieDatabase::class.java, "calorie-diary.db").addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4).build() }
    val repository by lazy { DiaryRepository(database, this) }
    val preferences by lazy { Preferences(this) }
}
