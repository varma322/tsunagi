package com.vce.tsunagi.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters

@Database(
    entities = [DeviceEntity::class, MessageEntity::class],
    version = 1,
    exportSchema = true,
)
@TypeConverters(SyncStatusConverter::class)
abstract class TsunagiDatabase : RoomDatabase() {
    abstract fun deviceDao(): DeviceDao
    abstract fun messageDao(): MessageDao

    companion object {
        private const val NAME = "tsunagi.db"

        @Volatile
        private var instance: TsunagiDatabase? = null

        fun get(context: Context): TsunagiDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    TsunagiDatabase::class.java,
                    NAME,
                ).build().also { instance = it }
            }
    }
}
