package com.hirebuddha.dialer.telecom

import android.app.role.RoleManager
import android.content.Context
import android.content.Intent

object DialerRole {
    fun isHeld(context: Context): Boolean =
        context.getSystemService(RoleManager::class.java).let { it.isRoleAvailable(RoleManager.ROLE_DIALER) && it.isRoleHeld(RoleManager.ROLE_DIALER) }

    fun requestIntent(context: Context): Intent =
        context.getSystemService(RoleManager::class.java).createRequestRoleIntent(RoleManager.ROLE_DIALER)
}
